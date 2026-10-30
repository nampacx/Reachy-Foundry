import threading
from unittest.mock import MagicMock

import numpy as np

from reachy_foundry_agent.follow import PersonFollower
from reachy_foundry_agent.robot_tools import RobotTools

W, H = 640, 480


def make_follower(hit, should_track=lambda: True, lock=None):
    mini = MagicMock()
    mini.media.get_frame.return_value = np.zeros((H, W, 3), dtype=np.uint8)
    detector = MagicMock()
    detector.find_person.return_value = hit
    return PersonFollower(mini, detector, lock or threading.Lock(), should_track), mini


def test_follower_moves_part_of_the_way_towards_the_person():
    follower, mini = make_follower((620.0, 240.0))  # far right, vertically centred
    assert follower.step() == "moved"
    u, v = mini.look_at_image.call_args.args
    assert W / 2 < u < 620 and v == H / 2  # gain < 1: does not jump all the way


def test_follower_stays_still_when_person_is_centred_or_gone():
    follower, mini = make_follower((W / 2 + 10, H / 2 - 10))
    assert follower.step() == "centred"
    follower, mini = make_follower(None)
    assert follower.step() == "no person"
    mini.look_at_image.assert_not_called()


def test_follower_pauses_and_yields_to_other_motions():
    follower, mini = make_follower((10.0, 10.0), should_track=lambda: False)
    assert follower.step() == "paused"
    mini.media.get_frame.assert_not_called()  # no camera use while paused (e.g. asleep)
    lock = threading.Lock()
    follower, mini = make_follower((10.0, 10.0), lock=lock)
    with lock:  # a gesture or emotion owns the head
        assert follower.step() == "busy"
    mini.look_at_image.assert_not_called()
    assert follower.step() == "moved"
    assert not lock.locked()


def _robot():
    mini = MagicMock()
    mini.media.get_frame.return_value = np.zeros((H, W, 3), dtype=np.uint8)
    detector = MagicMock()
    detector.find_person.return_value = (10.0, 10.0)
    return RobotTools(mini, None, threading.Event(), detector=detector), mini


def test_robot_follows_only_while_awake_and_enabled():
    robot, mini = _robot()
    assert robot._follower.step() == "moved"
    robot.go_to_sleep()
    assert robot._follower.step() == "paused"
    robot.wake_up()
    robot._hold_until = 0.0
    assert robot.stop_following() == "stopped following"
    assert robot._follower.step() == "paused"
    assert robot.follow_person() == "following the person"
    assert robot._follower.step() == "moved"


def test_gestures_hold_off_the_follower():
    robot, _ = _robot()
    robot.move_head("left")  # the user asked to look left: do not snap straight back
    assert robot._follower.step() == "paused"


def test_follow_tools_registered_only_with_detector():
    robot, _ = _robot()
    names = {t.name for t in robot.as_tools()}
    assert {"follow_person", "stop_following", "look_at_person"} <= names
    plain = RobotTools(MagicMock(), None, threading.Event())
    assert plain._follower is None and "follow_person" not in {t.name for t in plain.as_tools()}
    plain.start_follower(threading.Event())  # no-op without a detector
