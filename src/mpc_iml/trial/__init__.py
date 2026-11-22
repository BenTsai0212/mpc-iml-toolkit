"""Blind comparison trials of `ensemble` (#197).

A trial plays a list of conditions (named sets of `ensemble` controls) in a
counterbalanced order, under code letters given by play order, and keeps one
session file per trial. `spec` reads trial files, `order` picks the order and the
letters, `session` writes and reads session files, `run` plays a trial, and
`report` summarizes session files.
"""
