# coding: utf-8
import argparse
from datetime import datetime
import SFC

__author__ = 'Joaquim Leitão'

# System imports
import time
import traceback
import sys
import threading
import Pyro4
import PID

# Import daqmxlib and other private libraries
import daqmxlib
import utils

TIMER_STEP = 1.0
LIMIT_FAILS = 540
global MIN_READ_VALUE
global MAX_READ_VALUE
global can_actuate_ao0
global can_actuate_ao1
MIN_READ_VALUE = -6
MAX_READ_VALUE = -5
can_actuate_ao0 = True
can_actuate_ao1 = True


def check_board(board):
    global MIN_READ_VALUE
    global can_actuate_ao0
    global can_actuate_ao1

    while True:
        try:
            readings = board.read_all()

            readings_ai0 = readings['ai0']
            readings_ai1 = readings['ai1']

            readings_ai0 = readings_ai0[0]
            readings_ai1 = readings_ai1[0]

            print "Read " + str(readings_ai0) + " and " + str(readings_ai1) + " Current Number of Failures: " + \
                  str(board.sensor_down_count)

            if can_actuate_ao0 and readings_ai0 <= MIN_READ_VALUE:
                # Cannot actuate anymore in ai0
                print "Cannot actuate anymore in ai0"
                can_actuate_ao0 = False
                # Send 0 to ao0
                board.actuator.execute_task("ao0", 1, 0)
            elif (not can_actuate_ao0) and readings_ai0 >= MAX_READ_VALUE:
                # Can actuate back in ai0
                print "Can actuate back in ai0"
                can_actuate_ao0 = True

            if can_actuate_ao1 and readings_ai1 <= MIN_READ_VALUE:
                # Cannot actuate anymore in ai1
                print "Cannot actuate anymore in ai1"
                can_actuate_ao1 = False
                # Send 0 to ao1
                board.actuator.execute_task("ao1", 1, 0)
            elif (not can_actuate_ao1) and readings_ai1 >= MAX_READ_VALUE:
                # Can actuate back in ai1
                print "Can actuate back in ai1"
                can_actuate_ao1 = True

            # Reached the end of the loop without major problems
            board.sensor_down_count = 0
        except Exception, e:
            print "Board is not connected!\n" + str(e)

            # sensor_down_count will only be -1 when a failure occurs with no correct behaviour after
            if board.sensor_down_count != -1:
                board.sensor_down_count += 1
            if board.sensor_down_count == LIMIT_FAILS:
                utils.send_email("NI-USB Board", "The Board has been down for " + str(board.sensor_down_count) +
                                 " seconds!\nPlease check the connection as soon as possible")
                board.sensor_down_count = -1
                print "Sended email"
            print board.sensor_down_count
        time.sleep(TIMER_STEP)


class BoardInteraction(object):
    def __init__(self, device="dev2"):
        """
        Class constrcutor
        """
        self.device = device
        # Create the actuator and the reader with all the channels
        self.actuator = daqmxlib.Actuator(["ao0", "ao1"], device=self.device)
        self.reader = daqmxlib.Reader({"ai0": 1, "ai1": 1, "ai2": 1, "ai3": 1, "ai4": 1, "ai5": 1, "ai6": 1, "ai7": 1},
                                      device=self.device)
        self.sensor_down_count = 0
        self.controller_thread = None

    def execute_task(self, name, num_samps_channel, message, auto_start=1, timeout=0):
        # Check if we can actuate in the given channel
        if name == "ao0" and not can_actuate_ao0:
            return False
        elif name == "ao1" and not can_actuate_ao1:
            return False
        print 'Executing task ' + str(name), message
        return self.actuator.execute_task(name, num_samps_channel, message, auto_start, timeout)

    def SFC_controller_input(self, user, K, U, TS=0.05, SAMPLES=100):
        output = {}
        if self.controller_thread is None or self.controller_thread.isAlive() == False or self.controller_thread.failed[
            "status"]:
            self.controller_thread = SFC.ControllerThread(user, K, U, TS=TS, SAMPLES=SAMPLES)
            self.controller_thread.start()
            output["completed"] = self.controller_thread.completed
            output["controller"] = self.controller_thread.type
            output["success"] = True
            output["message"] = "Actuated successfully."
            output["status"] = 200
        else:
            output["message"] = "Controller is still running."
            output["success"] = False
            output["status"] = 200

        output["timestamp"] = str(datetime.now())
        return output

    def PID_controller_input(self, user, P=0.2, I=0.0, D=0.0, SETPOINT=1.0, TS=0.05, SAMPLES=100, WAVETYPE={}):
        output = {}
        if self.controller_thread is None or self.controller_thread.isAlive() == False or self.controller_thread.failed[
            "status"]:
            self.controller_thread = PID.ControllerThread(daqmxlib.Reader({"ai0": 1}, device=self.device),
                                                          daqmxlib.Actuator(["ao0"], device=self.device), user,
                                                          P=P,
                                                          I=I, D=D, SETPOINT=SETPOINT,
                                                          TS=TS, SAMPLES=SAMPLES, WAVETYPE=WAVETYPE)
            self.controller_thread.start()

            output["completed"] = self.controller_thread.completed
            output["controller"] = self.controller_thread.type
            output["success"] = True
            output["message"] = "Actuated successfully."
            output["status"] = 200
        else:
            output["message"] = "Controller is still running."
            output["success"] = False
            output["status"] = 200

        output["timestamp"] = str(datetime.now())
        return output

    def controller_stop(self, user):
        if self.controller_thread is None or user != self.controller_thread.user:
            return {"success": False, "failed": True, "timestamp": str(datetime.now()), "status": 404,
                    "reason": "No controller is running.", "message": "No controller is running."}
        self.controller_thread.abort = True
        self.controller_thread.join()

        return {"success": True, "timestamp": str(datetime.now()), "status": 200}

    def controller_output(self, user):
        try:
            if self.controller_thread is None or user != self.controller_thread.user:
                return {"success": False, "failed": True, "timestamp": str(datetime.now()), "status": 404,
                        "reason": "No controller is running.", "message": "No controller is running."}

            if self.controller_thread.failed["status"]:
                output = {"success": False,
                          "timestamp": str(datetime.now()),
                          "failed": True,
                          "reason": self.controller_thread.failed["reason"]}
            else:
                output = {"success": True,
                          "timestamp": str(datetime.now()),
                          "failed": False}

            output["completed"] = self.controller_thread.completed
            if self.controller_thread.completed:
                output["message"] = "The experiment has ended."
                output["status"] = 200
            else:
                output["message"] = "The controller is running."
                output["status"] = 200

            if self.controller_thread.type.lower() == "pid":
                output.update(
                    {"input": self.controller_thread.feedback_list, "output": self.controller_thread.output_list,
                     "time_list": self.controller_thread.time_list,
                     "setpoint_list": self.controller_thread.setpoint_list, "ts": self.controller_thread.TS,
                     "setpoint": self.controller_thread.SETPOINT,
                     "samples": self.controller_thread.SAMPLES, "P": self.controller_thread.P,
                     "I": self.controller_thread.I, "D": self.controller_thread.D,
                     "WAVETYPE": self.controller_thread.WAVETYPE,
                     "input_device": self.controller_thread.input, "output_device": self.controller_thread.output})
            elif self.controller_thread.type.lower() == "sfc":
                output.update({"K": self.controller_thread.K, "U": self.controller_thread.U,
                               "samples": self.controller_thread.SAMPLES, "ts": self.controller_thread.TS})

            return output
        except Exception:
            traceback.print_exc()

    def read_all(self, timeout=0.01, num_samples=None):
        return self.reader.read_all(timeout, num_samples)

    def change_collected_samples(self, physical_channel, number_samples):
        return self.reader.change_collected_samples(physical_channel, number_samples)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', help="Device identification.", default="dev2")
    parser.add_argument('--port', help="Device identification.", default="6000")
    args = parser.parse_args()
    board_interaction = BoardInteraction(device=args.device)

    # Make a Pyro4 daemon
    daemon = Pyro4.Daemon(host='0.0.0.0', port=int(args.port))
    # Register the greeting object as a Pyro4 object
    uri = daemon.register(board_interaction, 'NIBoard_' + args.device)

    print "Going to create thread"

    #thread = threading.Thread(target=check_board, args=(board_interaction,))
    #thread.start()

    # Print the uri so we can use it in the client later
    print "Ready. Object uri =", uri

    # Start the event loop of the server to wait for calls
    daemon.requestLoop()
