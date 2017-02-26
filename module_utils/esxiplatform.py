import os
import sys

def system():
	return "Esxi"

def release(): 
	return os.uname()[2]

def machine(): 
	return os.uname()[4]

def python_version(): 
	pyversion = sys.version_info
	return "%s.%s.%s" % (pyversion[0], pyversion[1], pyversion[2])

def node(): 
	return os.uname()[1]

def architecture(): 
	if sys.maxsize > 2**32:
		return ('64bit', 'ELF')
	else:
		return ('32bit', 'ELF')

def uname():
	osuname = os.uname()
	return osuname + osuname[-1:]

def version(): 
	return os.uname()[3]

def main():
    print "system: %s" % system()
    print "release: %s" % release()
    print "machine: %s" % machine()
    print "python_version: %s" % python_version()
    print "node: %s" % node()
    print "architecture: %s" % str(architecture())
    print "uname: %s" % str(uname())
    print "version: %s" % version()

if __name__ == "__main__":
    main()
