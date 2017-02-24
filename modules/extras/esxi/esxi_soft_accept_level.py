#!/usr/bin/python
import shlex
from subprocess import Popen, PIPE
import json
import sys


def parseArgs(args_file):
    args_data = file(args_file).read()

    # for this module, we're going to do key=value style arguments
    # this is up to each module to decide what it wants, but all
    # core modules besides 'command' and 'shell' take key=value
    # so this is highly recommended

    arguments = shlex.split(args_data)
    args = {}
    for arg in arguments:

        # ignore any arguments without an equals in it
        if "=" in arg:

            (key, value) = arg.split("=")

            # if setting the time, the key 'time'
            # will contain the value we want to set the time to

            args[key] = value

    return args


def exitParamError(param):
    print json.dumps({
        "failed": True,
        "msg": "parameter %s is missing" % param
    })
    sys.exit(1)


def fail_json(param):
    print json.dumps({
        "failed": True,
        "msg": param
    })
    sys.exit(1)


def main():
    required_params = ["val"]

    args_file = sys.argv[1]
    args = parseArgs(args_file)

    for param in required_params:
        if param not in args:
            exitParamError(param)

    p = Popen(["esxcli", "software", "acceptance", "set", "--level=%s" % args["val"]], stdout=PIPE)
    output = p.communicate()[0]
    if p.returncode != 0:
        fail_json("Command failed with \n%s " % output)

    print json.dumps({
        "output": output,
        "changed": True
    })

if __name__ == '__main__':
    main()
