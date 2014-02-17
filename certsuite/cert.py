#!/usr/bin/env python

import ConfigParser
import StringIO
import argparse
import json
import mozdevice
import os
import socket
import sys
import wptserve
import time

"""Signalizes whether client has made initial connection to HTTP
server.

This is used for whilst waiting for the user to enter the correct
hostname and port to the device's browser.

"""
connected = False

headers = None

class Wait(object):
    """An explicit conditional utility class for waiting until a condition
    evalutes to true or not null.

    """

    def __init__(self, timeout=120, interval=0.1):
        self.timeout = timeout
        self.interval = interval
        self.end = time.time() + self.timeout

    def until(self, condition):
        rv = None
        start = time.time()

        while not time.time() >= self.end:
            try:
                rv = condition()
            except (KeyboardInterrupt, SystemExit) as e:
                raise e

            if isinstance(rv, bool) and not rv:
                time.sleep(self.interval)
                continue

            if rv is not None:
                return rv

            time.sleep(self.interval)

        raise Exception(
            "Timed out after %s seconds" % ((time.time() - start)))

def hostname():
    """Relies on ``/etc/hosts`` to find the fully qualified network
    hostname for this machine.

    """

    return socket.gethostbyname(socket.gethostname())

@wptserve.handlers.handler
def connect_handler(request, response):
    response.headers.set("Content-Type", "text/html")
    response.content = "<p><a href='/headers'>Click me</a></p>"

    global connected
    connected = True

@wptserve.handlers.handler
def headers_handler(request, response):
    response.headers.set("Content-Type", "text/html")
    response.content = "<p><a href='/install.html'>Click me</a></p>"

    global headers
    headers = request.headers

static_path = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "static"))

routes = [("GET", "/", connect_handler),
          ("GET", "/headers", headers_handler),
          ("GET", "/*", wptserve.handlers.file_handler)]

def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-reboot",
                        help="don't reboot device before running test",
                        action="store_true")
    args = parser.parse_args()

    report = {'buildprops': {}}

    # Step 1: Get device information
    try:
        dm = mozdevice.DeviceManagerADB()
    except mozdevice.DMError, e:
        print "Error connecting to device via adb (error: %s). Please be " \
            "sure device is connected and 'remote debugging' is enabled." % \
            e.msg
        sys.exit(1)

    # Reboot phone so it is in a fresh state
    if not args.no_reboot:
        print "Rebooting device..."
        dm.reboot(wait=True)

    # get build properties
    buildpropoutput = dm.shellCheckOutput(["cat", "/system/build.prop"])
    for buildprop in [line for line in buildpropoutput.splitlines() if '=' \
                          in line]:
        (prop, val) = buildprop.split('=')
        report['buildprops'][prop] = val

    # get process list
    report['processes_running'] = map(lambda p: { 'name': p[1], 'user': p[2] },
                                      dm.getProcessList())

    # kernel version
    report['kernel_version'] = dm.shellCheckOutput(["cat", "/proc/version"])

    # application.ini information
    appinicontents = dm.pullFile('/system/b2g/application.ini')
    sf = StringIO.StringIO(appinicontents)
    config = ConfigParser.ConfigParser()
    config.readfp(sf)
    report['application_ini'] = {}
    for section in config.sections():
        report['application_ini'][section] = dict(config.items(section))

    # Step 2: Navigate to local hosted web server to install app for
    # WebIDL iteration and fetching HTTP headers
    addr = (hostname(), 8080)
    httpd = wptserve.server.WebTestHttpd(
        host="0.0.0.0", port=addr[1], routes=routes, doc_root=static_path)
    httpd.start()

    print >> sys.stderr, "#1: Please navigate to http://%s:%d" % \
        (httpd.host, httpd.port)
    Wait().until(lambda: connected is True)

    print >> sys.stderr, \
        "#2: Please click the link on the web page to connect your device"
    Wait().until(lambda: headers is not None)
    report["headers"] = headers

    print >> sys.stderr, "#3: Please click the button to install the app"
    # TODO(ato): Add handler for device letting us know app's been installed

    print json.dumps(report)

if __name__ == "__main__":
    cli()
