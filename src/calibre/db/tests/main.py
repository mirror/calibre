#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:fdm=marker:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2013, Kovid Goyal <kovid at kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import unittest, os, argparse

def find_tests():
    return unittest.defaultTestLoader.discover(os.path.dirname(os.path.abspath(__file__)), pattern='*.py')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('name', nargs='?', default=None, help='The name of the test to run, for e.g. writing.WritingTest.many_many_basic')
    args = parser.parse_args()
    if args.name:
        unittest.TextTestRunner(verbosity=4).run(unittest.defaultTestLoader.loadTestsFromName(args.name))
    else:
        unittest.TextTestRunner(verbosity=4).run(find_tests())

