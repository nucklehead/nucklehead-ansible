#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2012, Daniel Hokka Zakrisson <daniel@hozac.com>
# (c) 2014, Ahti Kitsik <ak@ahtik.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
import json
import shlex
import shutil
import sys
from subprocess import Popen, PIPE

import datetime

import re
import os
import pipes
import tempfile

DOCUMENTATION = """
---
module: lineinfile
author:
    - "Daniel Hokka Zakrissoni (@dhozac)"
    - "Ahti Kitsik (@ahtik)"
extends_documentation_fragment:
    - files
    - validate
short_description: Ensure a particular line is in a file, or replace an
                   existing line using a back-referenced regular expression.
description:
  - This module will search a file for a line, and ensure that it is present or absent.
  - This is primarily useful when you want to change a single line in
    a file only. See the M(replace) module if you want to change
    multiple, similar lines; for other cases, see the M(copy) or
    M(template) modules.
version_added: "0.7"
options:
  dest:
    required: true
    aliases: [ name, destfile ]
    description:
      - The file to modify.
  regexp:
    required: false
    version_added: 1.7
    description:
      - The regular expression to look for in every line of the file. For
        C(state=present), the pattern to replace if found; only the last line
        found will be replaced. For C(state=absent), the pattern of the line
        to remove.  Uses Python regular expressions; see
        U(http://docs.python.org/2/library/re.html).
  state:
    required: false
    choices: [ present, absent ]
    default: "present"
    aliases: []
    description:
      - Whether the line should be there or not.
  line:
    required: false
    description:
      - Required for C(state=present). The line to insert/replace into the
        file. If C(backrefs) is set, may contain backreferences that will get
        expanded with the C(regexp) capture groups if the regexp matches.
  backrefs:
    required: false
    default: "no"
    choices: [ "yes", "no" ]
    version_added: "1.1"
    description:
      - Used with C(state=present). If set, line can contain backreferences
        (both positional and named) that will get populated if the C(regexp)
        matches. This flag changes the operation of the module slightly;
        C(insertbefore) and C(insertafter) will be ignored, and if the C(regexp)
        doesn't match anywhere in the file, the file will be left unchanged.
        If the C(regexp) does match, the last matching line will be replaced by
        the expanded line parameter.
  insertafter:
    required: false
    default: EOF
    description:
      - Used with C(state=present). If specified, the line will be inserted
        after the last match of specified regular expression. A special value is
        available; C(EOF) for inserting the line at the end of the file.
        If specified regular expresion has no matches, EOF will be used instead.
        May not be used with C(backrefs).
    choices: [ 'EOF', '*regex*' ]
  insertbefore:
    required: false
    version_added: "1.1"
    description:
      - Used with C(state=present). If specified, the line will be inserted
        before the last match of specified regular expression. A value is
        available; C(BOF) for inserting the line at the beginning of the file.
        If specified regular expresion has no matches, the line will be
        inserted at the end of the file.  May not be used with C(backrefs).
    choices: [ 'BOF', '*regex*' ]
  create:
    required: false
    choices: [ "yes", "no" ]
    default: "no"
    description:
      - Used with C(state=present). If specified, the file will be created
        if it does not already exist. By default it will fail if the file
        is missing.
  backup:
     required: false
     default: "no"
     choices: [ "yes", "no" ]
     description:
       - Create a backup file including the timestamp information so you can
         get the original file back if you somehow clobbered it incorrectly.
  others:
     description:
       - All arguments accepted by the M(file) module also work here.
     required: false
"""

EXAMPLES = r"""
- lineinfile: dest=/etc/selinux/config regexp=^SELINUX= line=SELINUX=enforcing

- lineinfile: dest=/etc/sudoers state=absent regexp="^%wheel"

- lineinfile: dest=/etc/hosts regexp='^127\.0\.0\.1' line='127.0.0.1 localhost' owner=root group=root mode=0644

- lineinfile: dest=/etc/httpd/conf/httpd.conf regexp="^Listen " insertafter="^#Listen " line="Listen 8080"

- lineinfile: dest=/etc/services regexp="^# port for http" insertbefore="^www.*80/tcp" line="# port for http by default"

# Add a line to a file if it does not exist, without passing regexp
- lineinfile: dest=/tmp/testfile line="192.168.1.99 foo.lab.net foo"

# Fully quoted because of the ': ' on the line. See the Gotchas in the YAML docs.
- lineinfile: "dest=/etc/sudoers state=present regexp='^%wheel' line='%wheel ALL=(ALL) NOPASSWD: ALL'"

- lineinfile: dest=/opt/jboss-as/bin/standalone.conf regexp='^(.*)Xms(\d+)m(.*)$' line='\1Xms${xms}m\3' backrefs=yes

# Validate the sudoers file before saving
- lineinfile: dest=/etc/sudoers state=present regexp='^%ADMIN ALL\=' line='%ADMIN ALL=(ALL) NOPASSWD:ALL' validate='visudo -cf %s'
"""

check_mode =False

def write_changes(params, lines,dest):

    tmpfd, tmpfile = tempfile.mkstemp()
    f = os.fdopen(tmpfd,'wb')
    f.writelines(lines)
    f.close()

    validate = params.get('validate', None)
    valid = not validate
    if validate:
        if "%s" not in validate:
            fail_json(params, msg="validate must contain %%s: %s" % (validate))
        proc= Popen([validate % tmpfile], stdout=PIPE, stderr=PIPE)
        (out, err) = proc.communicate()
        rc = proc.returncode
        valid = rc == 0
        if rc != 0:
            fail_json(params, msg='failed to validate: '
                                 'rc:%s error:%s' % (rc,err))
    if valid:
        shutil.move(tmpfile, os.path.realpath(dest))


def present(params, dest, regexp, line, insertafter, insertbefore, create,
            backup, backrefs):

    if not os.path.exists(dest):
        if not create:
            fail_json(params, rc=257, msg='Destination %s does not exist !' % dest)
        destpath = os.path.dirname(dest)
        if not os.path.exists(destpath) and not check_mode:
            os.makedirs(destpath)
        lines = []
    else:
        f = open(dest, 'rb')
        lines = f.readlines()
        f.close()

    msg = ""

    if regexp is not None:
        mre = re.compile(regexp)

    if insertafter not in (None, 'BOF', 'EOF'):
        insre = re.compile(insertafter)
    elif insertbefore not in (None, 'BOF'):
        insre = re.compile(insertbefore)
    else:
        insre = None

    # index[0] is the line num where regexp has been found
    # index[1] is the line num where insertafter/inserbefore has been found
    index = [-1, -1]
    m = None
    for lineno, cur_line in enumerate(lines):
        if regexp is not None:
            match_found = mre.search(cur_line)
        else:
            match_found = line == cur_line.rstrip('\r\n')
        if match_found:
            index[0] = lineno
            m = match_found
        elif insre is not None and insre.search(cur_line):
            if insertafter:
                # + 1 for the next line
                index[1] = lineno + 1
            if insertbefore:
                # + 1 for the previous line
                index[1] = lineno

    msg = ''
    changed = False
    # Regexp matched a line in the file
    if index[0] != -1:
        if backrefs:
            new_line = m.expand(line)
        else:
            # Don't do backref expansion if not asked.
            new_line = line

        if not new_line.endswith(os.linesep):
            new_line += os.linesep

        if lines[index[0]] != new_line:
            lines[index[0]] = new_line
            msg = 'line replaced'
            changed = True
    elif backrefs:
        # Do absolutely nothing, since it's not safe generating the line
        # without the regexp matching to populate the backrefs.
        pass
    # Add it to the beginning of the file
    elif insertbefore == 'BOF' or insertafter == 'BOF':
        lines.insert(0, line + os.linesep)
        msg = 'line added'
        changed = True
    # Add it to the end of the file if requested or
    # if insertafter/insertbefore didn't match anything
    # (so default behaviour is to add at the end)
    elif insertafter == 'EOF' or index[1] == -1:

        # If the file is not empty then ensure there's a newline before the added line
        if len(lines)>0 and not (lines[-1].endswith('\n') or lines[-1].endswith('\r')):
            lines.append(os.linesep)

        lines.append(line + os.linesep)
        msg = 'line added'
        changed = True
    # insert* matched, but not the regexp
    else:
        lines.insert(index[1], line + os.linesep)
        msg = 'line added'
        changed = True

    backupdest = ""
    if changed and not check_mode:
        if backup and os.path.exists(dest):
            backupdest = backup_local(dest)
        write_changes(params, lines, dest)

    if check_mode and not os.path.exists(dest):
        exit_json(params, changed=changed, msg=msg, backup=backupdest)

    exit_json(params, changed=changed, msg=msg, backup=backupdest)


def absent(params, dest, regexp, line, backup):

    if not os.path.exists(dest):
        exit_json(params, changed=False, msg="file not present")

    msg = ""

    f = open(dest, 'rb')
    lines = f.readlines()
    f.close()
    if regexp is not None:
        cre = re.compile(regexp)
    found = []

    def matcher(cur_line):
        if regexp is not None:
            match_found = cre.search(cur_line)
        else:
            match_found = line == cur_line.rstrip('\r\n')
        if match_found:
            found.append(cur_line)
        return not match_found

    lines = filter(matcher, lines)
    changed = len(found) > 0
    backupdest = ""
    if changed and not check_mode:
        if backup:
            backupdest = backup_local(dest)
        write_changes(params, lines, dest)

    if changed:
        msg = "%s line(s) removed" % len(found)

    exit_json(params, changed=changed, found=len(found), msg=msg, backup=backupdest)



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


def fail_json(params, **kwargs):
    ''' return from the module, with an error message '''
    assert 'msg' in kwargs, "implementation error -- msg to explain the error is required"
    kwargs['failed'] = True
    if 'invocation' not in kwargs:
        kwargs['invocation'] = {'module_args': params}
    print json.dumps(kwargs)
    sys.exit(1)


def exit_json(params, **kwargs):
    ''' return from the module, without error '''
    if not 'changed' in kwargs:
        kwargs['changed'] = False
    if 'invocation' not in kwargs:
        kwargs['invocation'] = {'module_args': params}
    print json.dumps(kwargs)
    sys.exit(0)


def backup_local(dest):
    fileName = os.path.basename(dest)
    bacupPath = "/tmp/%s" % fileName
    shutil.copy(dest, bacupPath)
    modifiedTime = os.path.getmtime(bacupPath)

    timeStamp = datetime.datetime.fromtimestamp(modifiedTime).strftime("%b-%d-%y-%H:%M:%S")
    shutil.move(bacupPath, bacupPath + "_" + timeStamp)

    return bacupPath + "_" + timeStamp


def main():
    required_params = ["dest"]
    default_params= {
        "state": "present",
        "backrefs": False,
        "create": False,
        "backup": False,
    }

    args_file = sys.argv[1]
    args = parseArgs(args_file)

    for param in required_params:
        if param not in args:
            exitParamError(param)

    default_params.update(args)

    # module = AnsibleModule(
    #     argument_spec=dict(
    #         dest=dict(required=True, aliases=['name', 'destfile']),
    #         state=dict(default='present', choices=['absent', 'present']),
    #         regexp=dict(default=None),
    #         line=dict(aliases=['value']),
    #         insertafter=dict(default=None),
    #         insertbefore=dict(default=None),
    #         backrefs=dict(default=False, type='bool'),
    #         create=dict(default=False, type='bool'),
    #         backup=dict(default=False, type='bool'),
    #         validate=dict(default=None, type='str'),
    #     ),
    #     mutually_exclusive=[['insertbefore', 'insertafter']],
    #     add_file_common_args=True,
    #     supports_check_mode=True
    # )

    params = default_params
    create = params['create']
    backup = params['backup']
    backrefs = params['backrefs']
    dest = os.path.expanduser(params['dest'])

    if os.path.isdir(dest):
        fail_json(params, rc=256, msg='Destination %s is a directory !' % dest)

    if params['state'] == 'present':
        if backrefs and params['regexp'] is None:
            fail_json(params, msg='regexp= is required with backrefs=true')

        if params.get('line', None) is None:
            fail_json(params, msg='line= is required with state=present')

        # Deal with the insertafter default value manually, to avoid errors
        # because of the mutually_exclusive mechanism.
        ins_bef, ins_aft = params['insertbefore'], params['insertafter']
        if ins_bef is None and ins_aft is None:
            ins_aft = 'EOF'

        line = params['line']

        present(params, dest, params['regexp'], line,
                ins_aft, ins_bef, create, backup, backrefs)
    else:
        if params['regexp'] is None and params.get('line', None) is None:
            fail_json(params, msg='one of line= or regexp= is required with state=absent')

        absent(params, dest, params['regexp'], params.get('line', None), backup)

if __name__ == '__main__':
    main()
