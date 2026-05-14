# -*- coding: utf-8 -*-
'''
 ***********************************************************
 * The Crew Add-on
 *
 * rewritten by cm 2024/12/20
 * last update cm 2025/11/06
 *
 * @file workers.py
 * @package script.module.thecrew
 *
 * @copyright (c) 2025, The Crew
 * @license GNU General Public License, version 3 (GPL-3.0)
 *
 ********************************************************cm*
'''

from threading import Thread as thread
from typing import Callable, Any

class Thread(thread):
    def __init__(self, target_function: Callable[..., Any], *function_args: Any) -> None:
        """
        Initialize a custom Thread object with a target function and its arguments.

        :param target_function: The callable function to execute in the thread.
        :param function_args: Variable arguments to pass to the target function.
        :raises ValueError: If target_function is not callable.
        """
        if not callable(target_function):
            raise ValueError("target_function must be callable")

        self.target_function = target_function  # Store for safe access
        self.args = function_args
        super().__init__(target=target_function, args=function_args)

    def __repr__(self) -> str:
        """Return a string representation of the thread for debugging."""
        return f"Thread(target={self.target_function.__name__ if self.target_function else 'None'}, args={repr(self.args)})"
