"""Wybór karty graficznej dla okna programu na komputerach z dwiema kartami."""

from __future__ import annotations

import sys

import pytest

from admenot.app import gpu


def test_two_cards_point_the_window_at_the_low_power_one():
    env: dict[str, str] = {}
    gpu.prefer_low_power_gpu(env, read=lambda: (0, 67882))
    assert env[gpu.BROWSER_ARGS] == "--use-adapter-luid=0,67882"


def test_one_card_leaves_the_window_alone():
    env: dict[str, str] = {}
    gpu.prefer_low_power_gpu(env, read=lambda: None)
    assert gpu.BROWSER_ARGS not in env


def test_arguments_already_set_are_kept():
    env = {gpu.BROWSER_ARGS: "--remote-debugging-port=9333"}
    gpu.prefer_low_power_gpu(env, read=lambda: (0, 67882))
    assert env[gpu.BROWSER_ARGS] == "--remote-debugging-port=9333 --use-adapter-luid=0,67882"


def test_a_card_chosen_by_hand_wins():
    env = {gpu.BROWSER_ARGS: "--use-adapter-luid=0,1"}
    gpu.prefer_low_power_gpu(env, read=lambda: (0, 67882))
    assert env[gpu.BROWSER_ARGS] == "--use-adapter-luid=0,1"


def test_a_failed_read_never_stops_the_program():
    def broken() -> None:
        raise OSError("no DXGI")

    env: dict[str, str] = {}
    gpu.prefer_low_power_gpu(env, read=broken)
    assert gpu.BROWSER_ARGS not in env


def test_only_real_cards_count():
    software = gpu.Adapter(luid=(0, 3), software=True)
    assert gpu.pick([gpu.Adapter((0, 1), False), software], (0, 1)) is None
    assert gpu.pick([gpu.Adapter((0, 1), False), gpu.Adapter((0, 2), False), software], (0, 2)) == (0, 2)


def test_a_preferred_card_that_is_not_real_is_ignored():
    adapters = [gpu.Adapter((0, 1), False), gpu.Adapter((0, 2), False), gpu.Adapter((0, 3), True)]
    assert gpu.pick(adapters, (0, 3)) is None
    assert gpu.pick(adapters, None) is None


@pytest.mark.skipif(sys.platform != "win32", reason="DXGI jest tylko na Windows")
def test_reading_this_computer_gives_a_luid_or_nothing():
    found = gpu.low_power_adapter()
    assert found is None or (len(found) == 2 and all(isinstance(part, int) for part in found))
