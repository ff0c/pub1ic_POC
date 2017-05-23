#!/usr/bin/python
# -*- coding: utf-8 -*-

# hyw@cert.org.cn
# based on auxiliary/scanner/smb/smb_ms17_010 Metasploit module
# based on https://github.com/RiskSense-Ops/MS17-010/blob/master/scanners/smb_ms17_010.py
# add CIDR、IP Files support
#

from ctypes import *
import socket
import struct
import logging

import binascii
import argparse
import threading

# Packets
negotiate_protocol_request = binascii.unhexlify("00000085ff534d4272000000001853c00000000000000000000000000000fffe00004000006200025043204e4554574f524b2050524f4752414d20312e3000024c414e4d414e312e30000257696e646f777320666f7220576f726b67726f75707320332e316100024c4d312e325830303200024c414e4d414e322e3100024e54204c4d20302e313200")
session_setup_request = binascii.unhexlify("00000088ff534d4273000000001807c00000000000000000000000000000fffe000040000dff00880004110a000000000000000100000000000000d40000004b000000000000570069006e0064006f007700730020003200300030003000200032003100390035000000570069006e0064006f007700730020003200300030003000200035002e0030000000")
tree_connect_request = binascii.unhexlify("00000060ff534d4275000000001807c00000000000000000000000000000fffe0008400004ff006000080001003500005c005c003100390032002e003100360038002e003100370035002e003100320038005c00490050004300240000003f3f3f3f3f00")
trans2_session_setup = binascii.unhexlify("0000004eff534d4232000000001807c00000000000000000000000000008fffe000841000f0c0000000100000000000000a6d9a40000000c00420000004e0001000e000d0000000000000000000000000000")

# Arguments
parser = argparse.ArgumentParser(description="MS17-010 Vul&DoublePulsar Infection Detector\n\n", formatter_class=argparse.RawTextHelpFormatter)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument('--ip', help='Single IP address to check')
group.add_argument('--file', help='File containing a list of IP addresses to check')
group.add_argument('--net', help='Network CIDR to check (requires python netaddr library)')
parser.add_argument('--timeout', help="Timeout on connection for socket in seconds", default=None)
parser.add_argument('--verbose', help="Verbose output for not vul hosts", action='store_true')
parser.add_argument('--threads', help="Number of connection threads when checking file of IPs (default 10)", default="10")
parser.add_argument('--uninstall', help="Uninstall DoublePulsar if found", action='store_true')

args = parser.parse_args()
ip = args.ip
filename = args.file
net = args.net
timeout = args.timeout
verbose = args.verbose
num_threads = int(args.threads)
uninstall = args.uninstall
semaphore = threading.BoundedSemaphore(value=num_threads)
print_lock = threading.Lock()


logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__file__)

class SMB_HEADER(Structure):
  """SMB Header decoder.
  """

  _pack_ = 1  # Alignment

  _fields_ = [
    ("server_component", c_uint32),
    ("smb_command", c_uint8),
    ("error_class", c_uint8),
    ("reserved1", c_uint8),
    ("error_code", c_uint16),
    ("flags", c_uint8),
    ("flags2", c_uint16),
    ("process_id_high", c_uint16),
    ("signature", c_uint64),
    ("reserved2", c_uint16),
    ("tree_id", c_uint16),
    ("process_id", c_uint16),
    ("user_id", c_uint16),
    ("multiplex_id", c_uint16)
  ]

  def __new__(self, buffer=None):
    return self.from_buffer_copy(buffer)

  def __init__(self, buffer):
    log.debug("server_component : %04x" % self.server_component)
    log.debug("smb_command      : %01x" % self.smb_command)
    log.debug("error_class      : %01x" % self.error_class)
    log.debug("error_code       : %02x" % self.error_code)
    log.debug("flags            : %01x" % self.flags)
    log.debug("flags2           : %02x" % self.flags2)
    log.debug("process_id_high  : %02x" % self.process_id_high)
    log.debug("signature        : %08x" % self.signature)
    log.debug("reserved2        : %02x" % self.reserved2)
    log.debug("tree_id          : %02x" % self.tree_id)
    log.debug("process_id       : %02x" % self.process_id)
    log.debug("user_id          : %02x" % self.user_id)
    log.debug("multiplex_id     : %02x" % self.multiplex_id)


def generate_smb_proto_payload(*protos):
    """Generate SMB Protocol. Pakcet protos in order.
    """
    hexdata = []
    for proto in protos:
      hexdata.extend(proto)
    return "".join(hexdata)


# The arch is adjacent to the XOR key in the SMB signature
def calculate_doublepulsar_arch(s):
    if s & 0xffffffff00000000 == 0:
        return "x86 (32-bit)"
    else:
        return "x64 (64-bit)"

def calculate_doublepulsar_xor_key(s):
    """Calaculate Doublepulsar Xor Key
    """
    x = (2 * s ^ (((s & 0xff00 | (s << 16)) << 8) | (((s >> 16) | s & 0xff0000) >> 8)))
    x = x & 0xffffffff  # this line was added just to truncate to 32 bits
    return x


def negotiate_proto_request():
    """Generate a negotiate_proto_request packet.
    """
    log.debug("generate negotiate request")
    netbios = [
      '\x00',              # 'Message_Type'
      '\x00\x00\x54'       # 'Length'
    ]

    smb_header = [
      '\xFF\x53\x4D\x42',  # 'server_component': .SMB
      '\x72',              # 'smb_command': Negotiate Protocol
      '\x00\x00\x00\x00',  # 'nt_status'
      '\x18',              # 'flags'
      '\x01\x28',          # 'flags2'
      '\x00\x00',          # 'process_id_high'
      '\x00\x00\x00\x00\x00\x00\x00\x00',  # 'signature'
      '\x00\x00',          # 'reserved'
      '\x00\x00',          # 'tree_id'
      '\x2F\x4B',          # 'process_id'
      '\x00\x00',          # 'user_id'
      '\xC5\x5E'           # 'multiplex_id'
    ]

    negotiate_proto_request = [
      '\x00',              # 'word_count'
      '\x31\x00',          # 'byte_count'

      # Requested Dialects
      '\x02',              # 'dialet_buffer_format'
      '\x4C\x41\x4E\x4D\x41\x4E\x31\x2E\x30\x00',   # 'dialet_name': LANMAN1.0

      '\x02',              # 'dialet_buffer_format'
      '\x4C\x4D\x31\x2E\x32\x58\x30\x30\x32\x00',   # 'dialet_name': LM1.2X002

      '\x02',              # 'dialet_buffer_format'
      '\x4E\x54\x20\x4C\x41\x4E\x4D\x41\x4E\x20\x31\x2E\x30\x00',  # 'dialet_name3': NT LANMAN 1.0

      '\x02',              # 'dialet_buffer_format'
      '\x4E\x54\x20\x4C\x4D\x20\x30\x2E\x31\x32\x00'   # 'dialet_name4': NT LM 0.12
    ]

    return generate_smb_proto_payload(netbios, smb_header, negotiate_proto_request)


def session_setup_andx_request():
    """Generate session setuo andx request.
    """
    log.debug("generate session setup andx request")
    netbios = [
      '\x00',              # 'Message_Type'
      '\x00\x00\x63'       # 'Length'
    ]

    smb_header = [
      '\xFF\x53\x4D\x42',  # 'server_component': .SMB
      '\x73',              # 'smb_command': Session Setup AndX
      '\x00\x00\x00\x00',  # 'nt_status'
      '\x18',              # 'flags'
      '\x01\x20',          # 'flags2'
      '\x00\x00',          # 'process_id_high'
      '\x00\x00\x00\x00\x00\x00\x00\x00',  # 'signature'
      '\x00\x00',          # 'reserved'
      '\x00\x00',          # 'tree_id'
      '\x2F\x4B',          # 'process_id'
      '\x00\x00',          # 'user_id'
      '\xC5\x5E'           # 'multiplex_id'
    ]

    session_setup_andx_request = [
      '\x0D',              # Word Count
      '\xFF',              # AndXCommand: No further command
      '\x00',              # Reserved
      '\x00\x00',          # AndXOffset
      '\xDF\xFF',          # Max Buffer
      '\x02\x00',          # Max Mpx Count
      '\x01\x00',          # VC Number
      '\x00\x00\x00\x00',  # Session Key
      '\x00\x00',          # ANSI Password Length
      '\x00\x00',          # Unicode Password Length
      '\x00\x00\x00\x00',  # Reserved
      '\x40\x00\x00\x00',  # Capabilities
      '\x26\x00',          # Byte Count
      '\x00',              # Account
      '\x2e\x00',          # Primary Domain
      '\x57\x69\x6e\x64\x6f\x77\x73\x20\x32\x30\x30\x30\x20\x32\x31\x39\x35\x00',    # Native OS: Windows 2000 2195
      '\x57\x69\x6e\x64\x6f\x77\x73\x20\x32\x30\x30\x30\x20\x35\x2e\x30\x00',        # Native OS: Windows 2000 5.0
    ]

    return generate_smb_proto_payload(netbios, smb_header, session_setup_andx_request)


def tree_connect_andx_request(ip, userid):
    """Generate tree connect andx request.
    """
    log.debug("generate tree connect andx request")

    netbios = [
      '\x00',              # 'Message_Type'
      '\x00\x00\x47'       # 'Length'
    ]

    smb_header = [
      '\xFF\x53\x4D\x42',  # 'server_component': .SMB
      '\x75',              # 'smb_command': Tree Connect AndX
      '\x00\x00\x00\x00',  # 'nt_status'
      '\x18',              # 'flags'
      '\x01\x20',          # 'flags2'
      '\x00\x00',          # 'process_id_high'
      '\x00\x00\x00\x00\x00\x00\x00\x00',  # 'signature'
      '\x00\x00',          # 'reserved'
      '\x00\x00',          # 'tree_id'
      '\x2F\x4B',          # 'process_id'
      userid,              # 'user_id'
      '\xC5\x5E'           # 'multiplex_id'
    ]

    ipc = "\\\\{}\IPC$\x00".format(ip)
    log.debug("Connecting to {} with UID = {}".format(ipc, userid))

    tree_connect_andx_request = [
      '\x04',              # Word Count
      '\xFF',              # AndXCommand: No further commands
      '\x00',              # Reserved
      '\x00\x00',          # AndXOffset
      '\x00\x00',          # Flags
      '\x01\x00',          # Password Length
      '\x1C\x00',          # Byte Count
      '\x00',              # Password
      ipc.encode(),        # \\xxx.xxx.xxx.xxx\IPC$
      '\x3f\x3f\x3f\x3f\x3f\x00'   # Service
    ]

    length = len("".join(smb_header)) + len("".join(tree_connect_andx_request))
    # netbios[1] = '\x00' + struct.pack('>H', length)
    netbios[1] = struct.pack(">L", length)[-3:]

    return generate_smb_proto_payload(netbios, smb_header, tree_connect_andx_request)


def peeknamedpipe_request(treeid, processid, userid, multiplex_id):
    """Generate tran2 request
    """
    log.debug("generate peeknamedpipe request")
    netbios = [
      '\x00',              # 'Message_Type'
      '\x00\x00\x4a'       # 'Length'
    ]

    smb_header = [
      '\xFF\x53\x4D\x42',  # 'server_component': .SMB
      '\x25',              # 'smb_command': Trans2
      '\x00\x00\x00\x00',  # 'nt_status'
      '\x18',              # 'flags'
      '\x01\x28',          # 'flags2'
      '\x00\x00',          # 'process_id_high'
      '\x00\x00\x00\x00\x00\x00\x00\x00',  # 'signature'
      '\x00\x00',          # 'reserved'
      treeid,
      processid,
      userid,
      multiplex_id
    ]

    tran_request = [
      '\x10',              # Word Count
      '\x00\x00',          # Total Parameter Count
      '\x00\x00',          # Total Data Count
      '\xff\xff',          # Max Parameter Count
      '\xff\xff',          # Max Data Count
      '\x00',              # Max Setup Count
      '\x00',              # Reserved
      '\x00\x00',          # Flags
      '\x00\x00\x00\x00',  # Timeout: Return immediately
      '\x00\x00',          # Reversed
      '\x00\x00',          # Parameter Count
      '\x4a\x00',          # Parameter Offset
      '\x00\x00',          # Data Count
      '\x4a\x00',          # Data Offset
      '\x02',              # Setup Count
      '\x00',              # Reversed
      '\x23\x00',          # SMB Pipe Protocol: Function: PeekNamedPipe (0x0023)
      '\x00\x00',          # SMB Pipe Protocol: FID
      '\x07\x00',
      '\x5c\x50\x49\x50\x45\x5c\x00'  # \PIPE\
    ]

    return generate_smb_proto_payload(netbios, smb_header, tran_request)


def trans2_request(treeid, processid, userid, multiplex_id):
    """Generate trans2 request.
    """
    log.debug("generate tran2 request")
    netbios = [
      '\x00',              # 'Message_Type'
      '\x00\x00\x4f'       # 'Length'
    ]

    smb_header = [
      '\xFF\x53\x4D\x42',  # 'server_component': .SMB
      '\x32',              # 'smb_command': Trans2
      '\x00\x00\x00\x00',  # 'nt_status'
      '\x18',              # 'flags'
      '\x07\xc0',          # 'flags2'
      '\x00\x00',          # 'process_id_high'
      '\x00\x00\x00\x00\x00\x00\x00\x00',  # 'signature'
      '\x00\x00',          # 'reserved'
      treeid,
      processid,
      userid,
      multiplex_id
    ]

    trans2_request = [
      '\x0f',              # Word Count
      '\x0c\x00',          # Total Parameter Count
      '\x00\x00',          # Total Data Count
      '\x01\x00',          # Max Parameter Count
      '\x00\x00',          # Max Data Count
      '\x00',              # Max Setup Count
      '\x00',              # Reserved
      '\x00\x00',          # Flags
      '\xa6\xd9\xa4\x00',  # Timeout: 3 hours, 3.622 seconds
      '\x00\x00',          # Reversed
      '\x0c\x00',          # Parameter Count
      '\x42\x00',          # Parameter Offset
      '\x00\x00',          # Data Count
      '\x4e\x00',          # Data Offset
      '\x01',              # Setup Count
      '\x00',              # Reserved
      '\x0e\x00',          # subcommand: SESSION_SETUP
      '\x00\x00',          # Byte Count
      '\x0c\x00' + '\x00' * 12
    ]

    return generate_smb_proto_payload(netbios, smb_header, trans2_request)

def check_dp(ip):
    global negotiate_protocol_request, session_setup_request, tree_connect_request, trans2_session_setup, timeout, verbose
    
    # Connect to socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(float(timeout) if timeout else None)
    host = ip
    port = 445
    s.connect((host, port))
    
    # Send/receive negotiate protocol request
    s.send(negotiate_protocol_request)
    s.recv(1024)

    # Send/receive session setup request
    s.send(session_setup_request)
    session_setup_response = s.recv(1024)

    # Extract user ID from session setup response
    user_id = session_setup_response[32:34]

    # Replace user ID in tree connect request packet
    modified_tree_connect_request = list(tree_connect_request)
    modified_tree_connect_request[32] = user_id[0]
    modified_tree_connect_request[33] = user_id[1]
    modified_tree_connect_request = "".join(modified_tree_connect_request)

    # Send tree connect request
    s.send(modified_tree_connect_request)
    tree_connect_response = s.recv(1024)

    # Extract tree ID from response
    tree_id = tree_connect_response[28:30]

    # Replace tree ID and user ID in trans2 session setup packet
    modified_trans2_session_setup = list(trans2_session_setup)
    modified_trans2_session_setup[28] = tree_id[0]
    modified_trans2_session_setup[29] = tree_id[1]
    modified_trans2_session_setup[32] = user_id[0]
    modified_trans2_session_setup[33] = user_id[1]
    modified_trans2_session_setup = "".join(modified_trans2_session_setup)

    # Send trans2 sessions setup request
    s.send(modified_trans2_session_setup)
    final_response = s.recv(1024)

    # Check for 0x51 response to indicate DOUBLEPULSAR infection
    if final_response[34] == "\x51":
        signature = final_response[18:26]
        signature_long = struct.unpack('<Q', signature)[0]
        key = calculate_doublepulsar_xor_key(signature_long)
        arch = calculate_doublepulsar_arch(signature_long)
        print "[!] [%s] DoublePulsar Deteced!!! Arch: %s, XOR Key: %s" % (ip, arch, hex(key))

        if uninstall:
            # Update MID and op code via timeout
            modified_trans2_session_setup = list(modified_trans2_session_setup)
            modified_trans2_session_setup[34] = "\x42"
            modified_trans2_session_setup[49] = "\x0e"
            modified_trans2_session_setup[50] = "\x69"
            modified_trans2_session_setup[51] = "\x00"
            modified_trans2_session_setup[52] = "\x00"
            modified_trans2_session_setup = "".join(modified_trans2_session_setup)

            s.send(modified_trans2_session_setup)
            uninstall_response = s.recv(1024)
            if uninstall_response[34] == "\x52":
              print "[+] [%s] DoublePulsar uninstall successful" % ip
              

    s.close()
    
def check(ip, port=445):
    """Check if MS17_010 SMB Vulnerability exists.
    """
    #print ip
    try:
        buffersize = 1024
        timeout = 0.5

        # Send smb request based on socket.
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect((ip, port))

        # SMB - Negotiate Protocol Request
        raw_proto = negotiate_proto_request()
        client.send(raw_proto)
        tcp_response = client.recv(buffersize)

        # SMB - Session Setup AndX Request
        raw_proto = session_setup_andx_request()
        client.send(raw_proto)
        tcp_response = client.recv(buffersize)

        netbios = tcp_response[:4]
        smb_header = tcp_response[4:36]   # SMB Header: 32 bytes
        smb = SMB_HEADER(smb_header)

        user_id = struct.pack('<H', smb.user_id)

        # parse native_os from Session Setup Andx Response
        session_setup_andx_response = tcp_response[36:]
        native_os = session_setup_andx_response[9:].split('\x00')[0]

        # SMB - Tree Connect AndX Request
        raw_proto = tree_connect_andx_request(ip, user_id)
        client.send(raw_proto)
        tcp_response = client.recv(buffersize)

        netbios = tcp_response[:4]
        smb_header = tcp_response[4:36]   # SMB Header: 32 bytes
        smb = SMB_HEADER(smb_header)

        tree_id = struct.pack('<H', smb.tree_id)
        process_id = struct.pack('<H', smb.process_id)
        user_id = struct.pack('<H', smb.user_id)
        multiplex_id = struct.pack('<H', smb.multiplex_id)

        # SMB - PeekNamedPipe Request
        raw_proto = peeknamedpipe_request(tree_id, process_id, user_id, multiplex_id)
        client.send(raw_proto)
        tcp_response = client.recv(buffersize)

        netbios = tcp_response[:4]
        smb_header = tcp_response[4:36]
        smb = SMB_HEADER(smb_header)

        # nt_status = smb_header[5:9]
        nt_status = struct.pack('BBH', smb.error_class, smb.reserved1, smb.error_code)

        # 0xC0000205 - STATUS_INSUFF_SERVER_RESOURCES - vulnerable
        # 0xC0000008 - STATUS_INVALID_HANDLE
        # 0xC0000022 - STATUS_ACCESS_DENIED

        if nt_status == '\x05\x02\x00\xc0':
            log.info("[+] [{}] is likely VULNERABLE to MS17-010! ({})".format(ip, native_os))

            # vulnerable to MS17-010, check for DoublePulsar infection
            check_dp(ip)
            
            
        elif nt_status in ('\x08\x00\x00\xc0', '\x22\x00\x00\xc0'):
          if verbose:
          	log.info("[-] [{}] does NOT appear vulnerable".format(ip))
          	#pass
        else:
        	if verbose:
        		log.info("[-] [{}] Unable to detect if this host is vulnerable".format(ip))
          	#pass

    except Exception as err:
      #log.error("[-] [{}] Exception: {}".format(ip, err))
      pass
    finally:
      client.close()



def threaded_check(ip_address):
    global semaphore

    try:
        check(ip_address)
    except Exception as e:
        with print_lock:
            print "[ERROR] [%s] - %s" % (ip_address, e)
    finally:
        semaphore.release()

if ip:
    check(ip)

elif filename:
    with open(filename, "r") as fp:
        for line in fp:
            semaphore.acquire()
            ip_address = line.strip()
            t = threading.Thread(target=threaded_check, args=(ip_address,))
            t.start()

elif net:
    from netaddr import IPNetwork
    network = IPNetwork(net)
    for addr in network:
        # Skip the network and broadcast addresses
        if (network.size != 1) and ((addr == network.network) or (addr == network.broadcast)):
            continue
        semaphore.acquire()
        ip_address = str(addr)
        t = threading.Thread(target=threaded_check, args=(ip_address,))
        t.start()
        
## References

# https://blogs.technet.microsoft.com/msrc/2017/04/14/protecting-customers-and-evaluating-risk/
# https://www.rapid7.com/db/modules/auxiliary/scanner/smb/smb_ms17_010
# https://github.com/rapid7/metasploit-framework/blob/master/modules/auxiliary/scanner/smb/smb_ms17_010.rb
# https://www.symantec.com/security_response/vulnerability.jsp?bid=96707
# https://winprotocoldoc.blob.core.windows.net/productionwindowsarchives/MS-SMB2/[MS-SMB2]-151016.pdf
# https://msdn.microsoft.com/en-us/library/windows/desktop/aa365233(v=vs.85).aspx
# https://technet.microsoft.com/en-us/library/security/ms17-010.aspx
# https://community.rapid7.com/community/metasploit/blog/2017/04/03/introducing-rubysmb-the-protocol-library-nobody-else-wanted-to-write
# https://msdn.microsoft.com/en-us/library/ee441741.aspx
# https://github.com/countercept/doublepulsar-detection-script/blob/master/detect_doublepulsar_smb.py
# http://stackoverflow.com/questions/38735421/packing-an-integer-number-to-3-bytes-in-python
# https://zerosum0x0.blogspot.com/2017/04/doublepulsar-initial-smb-backdoor-ring.html
