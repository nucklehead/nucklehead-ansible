#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2012, Michael DeHaan <michael.dehaan@gmail.com>
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
import traceback
from subprocess import PIPE, Popen

import sys

import datetime

import os
import tempfile

import hashlib

AVAILABLE_HASH_ALGORITHMS = dict()
# python 2.7.9+ and 2.7.0+
for attribute in ('available_algorithms', 'algorithms'):
    algorithms = getattr(hashlib, attribute, None)
    if algorithms:
        break
if algorithms is None:
    # python 2.5+
    algorithms = ('md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512')
for algorithm in algorithms:
    AVAILABLE_HASH_ALGORITHMS[algorithm] = getattr(hashlib, algorithm)

DOCUMENTATION = '''
---
module: copy
version_added: "historical"
short_description: Copies files to remote locations.
description:
     - The M(copy) module copies a file on the local box to remote locations. Use the M(fetch) module to copy files from remote locations to the local box. If you need variable interpolation in copied files, use the M(template) module.
options:
  src:
    description:
      - Local path to a file to copy to the remote server; can be absolute or relative.
        If path is a directory, it is copied recursively. In this case, if path ends
        with "/", only inside contents of that directory are copied to destination.
        Otherwise, if it does not end with "/", the directory itself with all contents
        is copied. This behavior is similar to Rsync.
    required: false
    default: null
    aliases: []
  content:
    version_added: "1.1"
    description:
      - When used instead of 'src', sets the contents of a file directly to the specified value.
        This is for simple values, for anything complex or with formatting please switch to the template module.
    required: false
    default: null
  dest:
    description:
      - Remote absolute path where the file should be copied to. If src is a directory,
        this must be a directory too.
    required: true
    default: null
  backup:
    description:
      - Create a backup file including the timestamp information so you can get
        the original file back if you somehow clobbered it incorrectly.
    version_added: "0.7"
    required: false
    choices: [ "yes", "no" ]
    default: "no"
  force:
    description:
      - the default is C(yes), which will replace the remote file when contents
        are different than the source. If C(no), the file will only be transferred
        if the destination does not exist.
    version_added: "1.1"
    required: false
    choices: [ "yes", "no" ]
    default: "yes"
    aliases: [ "thirsty" ]
  directory_mode:
    description:
      - When doing a recursive copy set the mode for the directories. If this is not set we will use the system
        defaults. The mode is only set on directories which are newly created, and will not affect those that
        already existed.
    required: false
    version_added: "1.5"
  remote_src:
    description:
      - If False, it will search for src at originating/master machine, if True it will go to the remote/target machine for the src. Default is False.
      - Currently remote_src does not support recursive copying.
    choices: [ "True", "False" ]
    required: false
    default: "False"
    version_added: "2.0"
  follow:
    required: false
    default: "no"
    choices: [ "yes", "no" ]
    version_added: "1.8"
    description:
      - 'This flag indicates that filesystem links, if they exist, should be followed.'
extends_documentation_fragment:
    - files
    - validate
author:
    - "Ansible Core Team"
    - "Michael DeHaan"
notes:
   - The "copy" module recursively copy facility does not scale to lots (>hundreds) of files.
     For alternative, see synchronize module, which is a wrapper around rsync.
'''

EXAMPLES = '''
# Example from Ansible Playbooks
- copy: src=/srv/myfiles/foo.conf dest=/etc/foo.conf owner=foo group=foo mode=0644

# The same example as above, but using a symbolic mode equivalent to 0644
- copy: src=/srv/myfiles/foo.conf dest=/etc/foo.conf owner=foo group=foo mode="u=rw,g=r,o=r"

# Another symbolic mode example, adding some permissions and removing others
- copy: src=/srv/myfiles/foo.conf dest=/etc/foo.conf owner=foo group=foo mode="u+rw,g-wx,o-rwx"

# Copy a new "ntp.conf file into place, backing up the original if it differs from the copied version
- copy: src=/mine/ntp.conf dest=/etc/ntp.conf owner=root group=root mode=644 backup=yes

# Copy a new "sudoers" file into place, after passing validation with visudo
- copy: src=/mine/sudoers dest=/etc/sudoers validate='visudo -cf %s'
'''

RETURN = '''
dest:
    description: destination file/path
    returned: success
    type: string
    sample: "/path/to/file.txt"
src:
    description: source file used for the copy on the target machine
    returned: changed
    type: string
    sample: "/home/httpd/.ansible/tmp/ansible-tmp-1423796390.97-147729857856000/source"
md5sum:
    description: md5 checksum of the file after running copy
    returned: when supported
    type: string
    sample: "2a5aeecc61dc98c4d780b14b330e3282"
checksum:
    description: checksum of the file after running copy
    returned: success
    type: string
    sample: "6e642bb8dd5c2e027bf21dd923337cbb4214f827"
backup_file:
    description: name of backup file created
    returned: changed and if backup=yes
    type: string
    sample: "/path/to/file.txt.2015-02-12@22:09~"
gid:
    description: group id of the file, after execution
    returned: success
    type: int
    sample: 100
group:
    description: group of the file, after execution
    returned: success
    type: string
    sample: "httpd"
owner:
    description: owner of the file, after execution
    returned: success
    type: string
    sample: "httpd"
uid:
    description: owner id of the file, after execution
    returned: success
    type: int
    sample: 100
mode:
    description: permissions of the target, after execution
    returned: success
    type: string
    sample: "0644"
size:
    description: size of the target, after execution
    returned: success
    type: int
    sample: 1220
state:
    description: state of the target, after execution
    returned: success
    type: string
    sample: "file"
'''

def split_pre_existing_dir(dirname):
    '''
    Return the first pre-existing directory and a list of the new directories that will be created.
    '''

    head, tail = os.path.split(dirname)
    if not os.path.exists(head):
        (pre_existing_dir, new_directory_list) = split_pre_existing_dir(head)
    else:
        return (head, [ tail ])
    new_directory_list.append(tail)
    return (pre_existing_dir, new_directory_list)


def adjust_recursive_directory_permissions(pre_existing_dir, new_directory_list, directory_args, changed):
    '''
    Walk the new directories list and make sure that permissions are as we would expect
    '''

    if len(new_directory_list) > 0:
        working_dir = os.path.join(pre_existing_dir, new_directory_list.pop(0))
        directory_args['path'] = working_dir
        changed = adjust_recursive_directory_permissions(working_dir, new_directory_list, directory_args, changed)
    return changed


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


def digest_from_file(params, filename, algorithm):
    ''' Return hex digest of local file for a digest_method specified by name, or None if file is not present. '''
    if not os.path.exists(filename):
        return None
    if os.path.isdir(filename):
        fail_json(params, msg="attempted to take checksum of directory: %s" % filename)

    # preserve old behaviour where the third parameter was a hash algorithm object
    if hasattr(algorithm, 'hexdigest'):
        digest_method = algorithm
    else:
        try:
            digest_method = AVAILABLE_HASH_ALGORITHMS[algorithm]()
        except KeyError:
            fail_json(params, msg="Could not hash file '%s' with algorithm '%s'. Available algorithms: %s" %
                               (filename, algorithm, ', '.join(AVAILABLE_HASH_ALGORITHMS)))

    blocksize = 64 * 1024
    infile = open(filename, 'rb')
    block = infile.read(blocksize)
    while block:
        digest_method.update(block)
        block = infile.read(blocksize)
    infile.close()
    return digest_method.hexdigest()


def md5(params, filename):
    ''' Return MD5 hex digest of local file using digest_from_file().

    Do not use this function unless you have no other choice for:
        1) Optional backwards compatibility
        2) Compatibility with a third party protocol

    This function will not work on systems complying with FIPS-140-2.

    Most uses of this function can use the module.sha1 function instead.
    '''
    if 'md5' not in AVAILABLE_HASH_ALGORITHMS:
        raise ValueError('MD5 not available.  Possibly running in FIPS mode')
    return digest_from_file(params, filename, 'md5')


def sha1(params, filename):
    ''' Return SHA1 hex digest of local file using digest_from_file(). '''
    return digest_from_file(params, filename, 'sha1')


def sha256(params, filename):
    ''' Return SHA-256 hex digest of local file using digest_from_file(). '''
    return digest_from_file(params, filename, 'sha256')


def main():
    required_params = ["src", "dest"]
    default_params = {
        "force": False,
        "backup": False,
        "remote_src": False,
        "mode": None,
        "follow": False

    }

    args_file = sys.argv[1]
    args = parseArgs(args_file)

    for param in required_params:
        if param not in args:
            exitParamError(param)

    default_params.update(args)
    params = default_params

    # module = AnsibleModule(
    #     # not checking because of daisy chain to file module
    #     argument_spec=dict(
    #         src=dict(required=False),
    #         original_basename=dict(required=False),  # used to handle 'dest is a directory' via template, a slight hack
    #         content=dict(required=False, no_log=True),
    #         dest=dict(required=True),
    #         backup=dict(default=False, type='bool'),
    #         force=dict(default=True, aliases=['thirsty'], type='bool'),
    #         validate=dict(required=False, type='str'),
    #         directory_mode=dict(required=False),
    #         remote_src=dict(required=False, type='bool'),
    #     ),
    #     add_file_common_args=True,
    #     supports_check_mode=True,
    # )

    src    = os.path.expanduser(params['src'])
    dest   = os.path.expanduser(params['dest'])
    backup = params['backup']
    force  = params['force']
    original_basename = params.get('original_basename', None)
    validate = params.get('validate', None)
    follow = params['follow']
    mode   = params['mode']
    remote_src = params['remote_src']

    if not os.path.exists(src):
        fail_json(params, msg="Source %s not found" % (src))
    if not os.access(src, os.R_OK):
        fail_json(params, msg="Source %s not readable" % (src))
    if os.path.isdir(src):
        fail_json(params, msg="Remote copy does not support recursive copy of directory: %s" % (src))

    checksum_src = sha1(params, src)
    checksum_dest = None
    # Backwards compat only.  This will be None in FIPS mode
    try:
        md5sum_src = md5(params, src)
    except ValueError:
        md5sum_src = None

    changed = False

    # Special handling for recursive copy - create intermediate dirs
    if original_basename and dest.endswith(os.sep):
        dest = os.path.join(dest, original_basename)
        dirname = os.path.dirname(dest)
        if not os.path.exists(dirname) and os.path.isabs(dirname):
            (pre_existing_dir, new_directory_list) = split_pre_existing_dir(dirname)
            os.makedirs(dirname)

    if os.path.exists(dest):
        if os.path.islink(dest) and follow:
            dest = os.path.realpath(dest)
        if not force:
            exit_json(params, msg="file already exists", src=src, dest=dest, changed=False)
        if (os.path.isdir(dest)):
            basename = os.path.basename(src)
            if original_basename:
                basename = original_basename
            dest = os.path.join(dest, basename)
        if os.access(dest, os.R_OK):
            checksum_dest = sha1(params, dest)
    else:
        if not os.path.exists(os.path.dirname(dest)):
            try:
                # os.path.exists() can return false in some
                # circumstances where the directory does not have
                # the execute bit for the current user set, in
                # which case the stat() call will raise an OSError
                os.stat(os.path.dirname(dest))
            except OSError, e:
                if "permission denied" in str(e).lower():
                    fail_json(params, msg="Destination directory %s is not accessible" % (os.path.dirname(dest)))
            fail_json(params, msg="Destination directory %s does not exist" % (os.path.dirname(dest)))
    if not os.access(os.path.dirname(dest), os.W_OK):
        fail_json(params, msg="Destination %s not writable" % (os.path.dirname(dest)))

    backup_file = None

    if checksum_src != checksum_dest or os.path.islink(dest):
        try:
            if backup:
                if os.path.exists(dest):
                    backup_file = backup_local(dest)
            # allow for conversion from symlink.
            if os.path.islink(dest):
                os.unlink(dest)
                open(dest, 'w').close()
            if validate:
                # if we have a mode, make sure we set it on the temporary
                # file source as some validations may require it
                # FIXME: should we do the same for owner/group here too?
                if "%s" not in validate:
                    fail_json(params, msg="validate must contain %%s: %s" % (validate))
                proc = Popen([validate % src], stdout=PIPE, stderr=PIPE)
                (out, err) = proc.communicate()
                rc = proc.returncode
                if rc != 0:
                    fail_json(params, msg="failed to validate: rc:%s error:%s" % (rc,err))
            if remote_src:
                _, tmpdest = tempfile.mkstemp(dir=os.path.dirname(dest))
                shutil.copy2(src, tmpdest)
                shutil.move(tmpdest, dest)
            else:
                shutil.move(src, dest)
        except IOError:
            fail_json(params, msg="failed to copy: %s to %s" % (src, dest), traceback=traceback.format_exc())
        changed = True
    else:
        changed = False

    res_args = dict(
        dest = dest, src = src, md5sum = md5sum_src, checksum = checksum_src, changed = changed
    )
    if backup_file:
        res_args['backup_file'] = backup_file

    params['dest'] = dest

    exit_json(params, **res_args)

main()
