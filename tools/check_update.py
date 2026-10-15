#!/usr/bin/env python3
"""Update follows the main copy, and a running older engine is not treated as this one."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server
import updater

assert updater.update_plan("main", "aaa", "bbb", 0, False) == "update"
assert updater.update_plan("feature", "aaa", "bbb", 0, False) == "update"
assert updater.update_plan("main", "aaa", "aaa", 0, False) == "current"
assert updater.update_plan("main", "aaa", "bbb", 0, True) == "dirty"
assert updater.update_plan("main", "ccc", "bbb", 2, False) == "ahead"
# Another branch can move back to main; its own commits are not "ahead".
assert updater.update_plan("feature", "ccc", "bbb", 0, False) == "update"

assert server.same_build("abc123", "abc123")
assert not server.same_build(8, "abc123")
assert not server.same_build("8", "abc123")
assert not server.same_build(None, "abc123")
# The number the engine used to report never changed, so it must not count as this copy.
assert not server.same_build(8)
assert not server.same_build("8")

import app
assert app.window_url("http://127.0.0.1:8099", "abc123") == "http://127.0.0.1:8099?build=abc123"
assert app.window_url("http://127.0.0.1:8099?x=1", "abc123") == "http://127.0.0.1:8099?x=1&build=abc123"

print("update check ok")
