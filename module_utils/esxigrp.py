def getgrall():
    groups = []
    with open('/etc/group', 'r') as groupsFile:
        for line in groupsFile:
            groupInfo = line.rstrip().split(":")
            members = groupInfo[3].split(",")
            if len(members[0]) == 0:
                members = []
            groups.append(struct_group(groupInfo[2], members, groupInfo[0], groupInfo[1]))
    return groups

def getgrgid(gid):
    matches = filter(lambda group: group.gr_gid == gid, self.getgrall())
    return matches[0]

def getgrnam(name):
    matches = filter(lambda group: group.gr_name == name, self.getgrall())
    return matches[0]

class struct_group(object):
    def __init__(self, gr_gid=None, gr_mem=[], gr_name=None, gr_passwd=None):
        self.gr_gid = int(gr_gid)
        self.gr_mem = gr_mem
        self.gr_name = gr_name
        self.gr_passwd = gr_passwd

    def __str__(self):
        return "grp.struct_group(gr_name='%s', gr_passwd='%s', gr_gid=%d, gr_mem=%s)" %(self.gr_name, self.gr_passwd, self.gr_gid, str(self.gr_mem))

def main():
    print getgrall()

if __name__ == "__main__":
    main()
