#!/usr/bin/env python

# needs access to libtcc and math.h
# TODO: *get tcc errors (currently something like 'Unknown error 3217941984',
#                        this makes debugging painful)
#       *currently the compiled function accepts too many arguments silently
#       *implement multi-dimensional functions for frange
#       *list comprehension syntax for frange?
#       *configuration of path to libtcc.so/improve instructions
#       *add gcc support again (easier to set up than tcc)
#       *fix compiler warnings


# heavily inspired by http://www.cs.tut.fi/~ask/cinpy/

"""
Experimental module for compiling functions to machine code.
Can also be used to generate C code from SymPy expressions.
Depends on libtcc.

This code is experimental. It may have severe bugs. Due to the use of C, it's
able to crash your Python interpreter with obscure error messages.


Overview
========

clambdify:  compile a function to machine code (only useful for big functions)
frange:     evaluate a function on a range of numbers using machine code
cexpr:      translate a Python expression to a C expression
genfcode:   generate C code from a lambda string


Performance
===========

Python functions using the math module are *quite* fast. For simple functions
they are faster than functions compiled to machine code. So you should try
whether lambdify is fast enough for you.

Iterating is slow in Python (it's probably the biggest bottle neck).
frange allows you to iterate using machine code. This can result in huge
speedups. You might want to use NumPy: http://numpy.org/
For simple functions it's faster, but for big ones frange can be several times
more efficent.

You should try which solution is the best for your application.

You can run the included benchmarks to see the real performance on your machine.


Configuration
=============

You will probably need to compile libtcc on your own. Get the sources of tcc:

http://bellard.org/tcc/

Then run for example

$ ./configure
$ make
$ sudo make install
$ gcc -shared -Wl,-soname,libtcc.so -o libtcc.so libtcc.o
$ cp libtcc.so dir/to/compilef.py   # or change libtccpath in compilef.py

Sadly there seems to be no other way without using root privileges. If you are
to prove me wrong, please tell it on sympy@googlegroups.com.

You might try to run libtcc_test. If something went wrong there will be bad low
level Python errors probably crashing the interpreter. The error output will be
printed to stdout or stderr, which might be different to your Python shell.

Make sure that this module knows the path to libtcc.

If everything went right, all the tests will pass. Run this file to do so and
to see the results of some benchmarks.

"""

import os
import ctypes
from sympy import Symbol
from sympy.utilities.lambdify import lambdastr as getlambdastr

libtccpath = './libtcc.so'
# load libtcc TODO: better Windows support
libtcc = ctypes.cdll.LoadLibrary(libtccpath)
if not libtcc:
    raise ImportError, 'Could not load libtcc'
##mathh = '/usr/include/math.h' # usually tcc knows where to find math.h

def __getLeftRight(expr, index, oplength=1, stopchar='+-'):
    """
    Gets the expressions to the left and right of an operator.

    >>> __getLeftRight('1/(g(x)*3.5)**(x - a**x)/(x**2 + a)', 12,
    ...                oplength=2, stopchar='+-*/')
    ('(g(x)*3.5)', '(x - a**x)')

    """
    # assumes correct syntax
    # TODO: never repeat yourself
    # get left expression
    left = ''
    openbraces = 0
    for char in reversed(expr[:index]):
        if char == ' ': # skip whitespaces but keep them
            left = char + left
            continue
        elif char == ')':
            openbraces += 1
            left = char + left
        elif char == '(':
            if not openbraces: # happens when operator is in braces
                break
            openbraces -= 1
            left = char + left
        elif char in stopchar:
            if openbraces:
                left = char + left
                continue
            else:
                break
        else:
            left = char + left
    # get right expression
    right = ''
    openbraces = 0
    for char in expr[index+oplength:]:
        if char == ' ': # skip whitespaces but keep them
            right += char
            continue
        elif char == '(':
            openbraces += 1
            right += char
        elif char == ')':
            if not openbraces: # happens when operator is in braces
                break
            openbraces -= 1
            right += char
        elif char in stopchar:
            if openbraces:
                right += char
                continue
            else:
                break
        else:
            right += char
    return (left, right)

def cexpr(pyexpr):
    """
    Python math expression string -> C expression string
    """
    # TODO: better spacing
    while True:
        index = pyexpr.find('**')
        if index != -1:
            left, right = __getLeftRight(pyexpr, index, 2, '+-*/')
            pyexpr = pyexpr.replace(left + '**' + right, ' pow(%s, %s) '
                                    % (left.lstrip(), right.rstrip()))
        else:
            break
    # TODO: convert 'x**n' to 'x*x*...*x'
    # TODO: avoid integer division
    # TODO: use cse
    return pyexpr

def genfcode(lambdastr):
    """
    Python lambda string -> C function code
    """
    # TODO: verify lambda string
    # interpret lambda string
    varstr, fstr = lambdastr.split(': ')
    varstr = varstr.lstrip('lambda ')
    # generate C variable string
    cvars = varstr.split(',')
    cvarstr = ''
    for v in cvars:
        cvarstr += 'double %s, ' % v
    cvarstr = cvarstr.rstrip(', ')
    # convert function string to C syntax
    cfstr = cexpr(fstr)
    # generate C code
    code = """
inline double f(%s)
    {
    return %s;
    }
""" % (cvarstr, cfstr)
    return code

def __run(cmd):
    """
    Checks the exit code of a ran command.
    """
    if not cmd == 0:
        raise Exception, 'could not run libtcc command'

def _compile(code, argcount=None, fname='f', fprototype=None):
    """
    C code with function -> compiled function

    Supports all standard C math functions, pi and e.
    Function is assumed to get and return 'double' only.
    Uses libtcc.
    """
    # returned type and all arguments are double
    if fprototype:
        fprototype = ctypes.CFUNCTYPE(*fprototype)
    else:
        assert argcount, 'need argcount if no prototype is specified'
        fprototype = ctypes.CFUNCTYPE(*[ctypes.c_double]*(argcount+1))
    # see libtcc.h for API documentation
    tccstate = libtcc.tcc_new()
    __run(libtcc.tcc_set_output_type(tccstate, 0)) # output to memory
    ##print libtcc.tcc_add_library_path(tccstate, mathh) # could be dropped
    __run(libtcc.tcc_add_library(tccstate, 'm')) # use math.h FIXME: Windows
    # compile string
    __run(libtcc.tcc_compile_string(tccstate, code))
    __run(libtcc.tcc_relocate(tccstate)) # fails if link error
    # create C variable to get result
    symbol = ctypes.c_long()
    __run(libtcc.tcc_get_symbol(tccstate, ctypes.byref(symbol), fname))
    # return reference to C function
    return fprototype(symbol.value)

# expr needs to work with lambdastr
def clambdify(args, expr):
    """
    SymPy expression -> compiled function

    Supports all standard C math functions, pi and e.

    >>> from sympy import symbols, sqrt
    >>> x, y = symbols('xy')
    >>> cf = clambdify((x,y), sqrt(x*y))
    >>> cf(0.5, 4)
    1.4142135623730951
    """
    # convert function to lambda string
    s = getlambdastr(args, expr.evalf(21))
    # generate code
    code = """
# include <math.h>

# define pi M_PI
# define e M_E

%s
""" % genfcode(s)
    # compile code
    return _compile(code, len(args))

def frange(*args):
    """
    frange(lambdastr, [start,] stop[, step]) -> ctypes double array

    Evaluates function on range using machine code.
    Currently only one-dimensional functions are supported.

    For simple functions it's somewhat slower than NumPy.
    For big functions it can be several times faster.

    lambdastr has the same restrictions as in clambdify.

    >>> frange('lambda x: sqrt(x)', 1, 4) # doctest: +ELLIPSIS
    <__main__.c_double_Array_3 object at ...>
    >>> for i in _:
    ...     print i
    ...
    1.0
    1.41421356237
    1.73205080757
    """
    if len(args) > 4:
        raise TypeError, 'expected at most 4 arguments, got %i' % len(args)
    if len(args) < 2:
        raise TypeError, 'expected at least 2 argument, got %i' % len(args)
    # interpret arguments
    lambdastr = args[0]
    start = 0
    step = 1
    if len(args) == 2:
        stop = args[1]
    elif len(args) >= 3:
        start = args[1]
        stop = args[2]
    if len(args) == 4:
        step = args[3]
    assert start + step != start, \
           'step is too small and would cause an infinite loop'
    # determine length of resulting array
    # TODO: do this better
    length = stop - start
    if length % step == 0:
        length = length/step - 1 # exclude last one
    else:
        length = length//step
    if step > 0:
        if start < stop:
            length += 1 # include first one
    else:
        if start > stop:
            length += 1 # include first one
    if length < 0:
        length = 0
    assert length == int(length)
    length = int(length)
    # create array
    a = (ctypes.c_double * length)()
    # generate code
    vardef = 'int MAX; double x = %f;' % start
    loopbody = '*result = f(x); x += %f;' % step
    code = """
# include <math.h>

# define pi M_PI
# define e M_E

%s

void evalonrange(double *result, int n)
    {
    %s
    for (MAX = result + n; result < MAX; result++)
        {
        %s
        }
    }

""" % (genfcode(lambdastr), vardef, loopbody)
    # compile and run
    evalonrange = _compile(code, fname='evalonrange',
                           fprototype=[None, ctypes.c_void_p, ctypes.c_int])
    evalonrange(ctypes.byref(a), ctypes.c_int(length))
    # return ctypes array with results
    return a



def test_cexpr():
    expr = '1/(g(x)*3.5)**(x - a**x)/(x**2 + a)'
    assert cexpr(expr).replace(' ', '') == \
           '1/pow((g(x)*3.5),(x-pow(a,x)))/(pow(x,2)+a)'

from sympy import sqrt, pi, lambdify
def test_clambdify():
    x = Symbol('x')
    y = Symbol('y')
    z = Symbol('z')
    f1 = sqrt(x*y)
    pf1 = lambdify((x, y), f1, 'math')
    cf1 = clambdify((x, y), f1)
    for i in xrange(10):
        assert cf1(i, 10 - i) == pf1(i, 10 - i)
    f2 = (x - y) / z * pi
    pf2 = lambdify((x, y, z), f2, 'math')
    cf2 = clambdify((x, y, z), f2)
    assert round(pf2(1, 2, 3),  14) == round(cf2(1, 2, 3),  14)
    # FIXME: slight difference in precision

from math import exp, cos
def test_frange():
    fstr = 'lambda x: exp(x)*cos(x)**x'
    f = eval(fstr)
    a = frange(fstr, 30, 168, 3)
    args = range(30, 168, 3)
    assert len(a) == len(args)
    for i in xrange(len(a)):
        assert a[i] == f(args[i])
    assert len(frange('lambda x: x', 0, -10000)) == 0
    assert len(frange('lambda x: x', -1, -1, 0.0001)) == 0
    a = frange('lambda x: x', -5, 5, 0.1)
    b = range(-50, 50)
    assert len(a) == len(b)
    for i in xrange(len(a)):
        assert int(round(a[i]*10)) == b[i]
    a = frange('lambda x: x', 17, -9, -3)
    b = range(17, -9, -3)
    assert len(a) == len(b)
    for i in xrange(len(a)):
        assert a[i] == b[i]
    a = frange('lambda x: x', 2.7, -3.1, -1.01)
    b = range(270, -310, -101)
    assert len(a) == len(b)
    for i in xrange(len(a)):
        assert int(round(a[i]*100)) == b[i]
    assert frange('lambda x: x', 0.2, 0.1, -0.1)[0] == 0.2
    assert len(frange('lambda x: x', 0)) == 0
    assert len(frange('lambda x: x', 1000, -1)) == 0
    assert len(frange('lambda x: x', -1.23, 3.21, -0.0000001)) == 0
    try:
        frange()
        assert False
    except TypeError:
        pass
    try:
        frange(1, 2, 3, 4, 5)
        assert False
    except TypeError:
        pass

def benchmark():
    """
    Run some benchmarks for clambdify and frange.

    NumPy and Psyco are used as reference if available.
    """
    from time import time
    from timeit import Timer

    def fbenchmark(f, var=[Symbol('x')]):
        """
        Does some benchmarks with f using clambdify, lambdify and psyco.
        """
        global cf, pf, psyf
        start = time()
        cf = clambdify(var, f)
        print 'compile time (including sympy overhead): %f s' % (time() - start)
        pf = lambdify(var, f, 'math')
        psyf = None
        try:
            import psyco
            psyf = lambdify(var, f, 'math')
            psyco.bind(psyf)
        except ImportError:
            pass
        code = '''for x in (i/1000. for i in xrange(1000)):
        f(%s)''' % ('x,'*len(var)).rstrip(',')
        t1 = Timer(code, 'from __main__ import cf as f')
        t2 = Timer(code, 'from __main__ import pf as f')
        if psyf:
            t3 = Timer(code, 'from __main__ import psyf as f')
        else:
            t3 = None
        print 'for x = (0, 1, 2, ..., 999)/1000'
        print '20 times in 3 runs'
        print 'compiled:      %.4f %.4f %.4f' % tuple(t1.repeat(3, 20))
        print 'Python lambda: %.4f %.4f %.4f' % tuple(t2.repeat(3, 20))
        if t3:
            print 'Psyco lambda:  %.4f %.4f %.4f' % tuple(t3.repeat(3, 20))

    print 'big function:'
    from sympy import diff, exp, sin, cos, pi, lambdify
    x = Symbol('x')
##    f1 = diff(exp(x)**2 - sin(x)**pi, x) \
##        * x**12-2*x**3+2*exp(x**2)-3*x**7+4*exp(123+x-x**5+2*x**4) \
##        * ((x + pi)**5).expand()
    f1 = 2*exp(x**2) + x**12*(-pi*sin(x)**((-1) + pi)*cos(x) + 2*exp(2*x)) \
         + 4*(10*pi**3*x**2 + 10*pi**2*x**3 + 5*pi*x**4 + 5*x*pi**4 + pi**5 \
         + x**5)*exp(123 + x + 2*x**4 - x**5) - 2*x**3 - 3*x**7
    fbenchmark(f1)
    print
    print 'simple function:'
    y = Symbol('y')
    f2 = sqrt(x*y)+x*5
    fbenchmark(f2, [x,y])
    times = 100000
    fstr = 'exp(sin(exp(-x**2)) + sqrt(pi)*cos(x**5/(x**3-x**2+pi*x)))'
    print
    print 'frange with f(x) ='
    print fstr
    print 'for x=1, ..., %i' % times
    print 'in 3 runs including full compile time'
    t4 = Timer("frange('lambda x: %s', 0, %i)" % (fstr, times),
               'from __main__ import frange')
    try:
        import numpy
    except ImportError:
        numpy = None
    print 'frange:        %.4f %.4f %.4f' % tuple(t4.repeat(3, 1))
    if numpy:
        t5 = Timer('x = arange(%i); result = %s' % (times, fstr),
                   'from numpy import arange, sqrt, exp, sin, cos, exp, pi')
        print 'numpy:         %.4f %.4f %.4f' % tuple(t5.repeat(3, 1))
    # TODO: integration into fbenchmark

if __name__ == '__main__':
    if __debug__:
        print 'Running tests...',
        test_cexpr()
        test_clambdify()
        test_frange()
        import doctest
        doctest.testmod()
        print 'OK'
        print
    print 'Running benchmark...'
    benchmark()
