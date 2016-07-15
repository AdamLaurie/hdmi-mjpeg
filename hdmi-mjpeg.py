#! /usr/bin/env python

# HDMI network extender to MJPEG sniffer

# Adam Laurie <adam@algroup.co.uk> - 2016
# 
#  https://github.com/AdamLaurie/hdmi-mjpeg
#
# 1st cut: 15th July 2016
#
# code based on original:
#
#Packet sniffer in python
#For Linux - Sniffs all incoming and outgoing packets :)
#Silver Moon (m00n.silv3r@gmail.com)
#modified by danman


import signal
import socket, sys, os
from struct import *
import struct
import binascii
import time, datetime

UDP_IP = "192.168.168.55"
UDP_PORT = 48689
SHOST="0.0.0.0"
MESSAGE = "5446367A600200000000000303010026000000000234C2".decode('hex')

if not (len(sys.argv) == 2 or len(sys.argv) == 3):
	print 'usage: %s <file prefix> [minutes]' % sys.argv[0]
	exit(0)

print "UDP target IP:", UDP_IP
print "UDP keepalive port:", UDP_PORT

try:
	record_time= int(sys.argv[2])
	print 'Recording will cease after %d minutes' % record_time
except:
	record_time= None
end_time= None


Keepalive_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP socket for keepalives
Keepalive_sock.bind((SHOST, UDP_PORT)) # send from the correct port or it will be ignored

def signal_handler(signal, frame):
	print('\nFlushing buffers...')
	Audio.flush()
	os.fsync(Audio.fileno())
	Audio.close()
	print 'Audio: %d bytes' % Audio_Bytes
	Video.flush()
	os.fsync(Video.fileno())
	Video.close()
	print 'Video: %d bytes' % Video_Bytes
	sys.exit(0)

def keepalive():
	Keepalive_sock.sendto(MESSAGE, (UDP_IP, UDP_PORT))

#Convert a string of 6 characters of ethernet address into a dash separated hex string
def eth_addr (a) :
  b = "%.2x:%.2x:%.2x:%.2x:%.2x:%.2x" % (ord(a[0]) , ord(a[1]) , ord(a[2]), ord(a[3]), ord(a[4]) , ord(a[5]))
  return b

# detect quit
signal.signal(signal.SIGINT, signal_handler)

try:
    s = socket.socket( socket.AF_PACKET , socket.SOCK_RAW , socket.ntohs(0x0003))
except socket.error , msg:
    print 'Socket could not be created. Error Code : ' + str(msg[0]) + ' Message ' + msg[1]
    sys.exit()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
mreq = struct.pack("=4sl", socket.inet_aton("226.2.2.2"), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

sender="000b78006001".decode("hex")
Videostarted=0
Audio= open(sys.argv[1] + "-audio.dat","w")
print 'Audio:', sys.argv[1] + "-audio.dat"
Video= open(sys.argv[1] + "-video.dat","w")
print 'Video:', sys.argv[1] + "-video.dat"
Video_Bytes= 0
Audio_Bytes= 0

# keep track of dropped frames
frame_prev= None
part_prev= 0

packet_started= False
senderstarted= False
outbuf= ''
dropping= False

# receive a packet
while True:
    packet = s.recvfrom(65565)

    if not packet_started:
	print 'Listener active at', datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
	packet_started= True

    #packet string from tuple
    packet = packet[0]

    #parse ethernet header
    eth_length = 14

    eth_header = packet[:eth_length]
    eth = unpack('!6s6sH' , eth_header)
    eth_protocol = socket.ntohs(eth[2])

    if (packet[6:12] == sender) & (eth_protocol == 8) :

        #Parse IP header
        #take first 20 characters for the ip header
        ip_header = packet[eth_length:20+eth_length]

        #now unpack them :)
        iph = unpack('!BBHHHBBH4s4s' , ip_header)

        version_ihl = iph[0]
        version = version_ihl >> 4
        ihl = version_ihl & 0xF

        iph_length = ihl * 4

        ttl = iph[5]
        protocol = iph[6]
        s_addr = socket.inet_ntoa(iph[8]);
        d_addr = socket.inet_ntoa(iph[9]);

        #UDP packets
        if protocol == 17 :
		u = iph_length + eth_length
		udph_length = 8
		udp_header = packet[u:u+8]

		#now unpack them :)
		udph = unpack('!HHHH' , udp_header)

		source_port = udph[0]
		dest_port = udph[1]
		length = udph[2]
		checksum = udph[3]

		#get data from the packet
		h_size = eth_length + iph_length + udph_length
		data = packet[h_size:]

		# audio
		if (dest_port==2066) and Videostarted:
			Audio.write(data[16:])
			Audio_Bytes += len(data[16:])

		if (dest_port==2068):
			if not senderstarted:
				print 'Sender active at', datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
				senderstarted= True
			frame_n=ord(data[0])*256+ord(data[1])
			# data[2] is not part of the frame number - if it is set to 0x80 that means this is the last frame
			#part=ord(data[2])*256+ord(data[3])
			part=ord(data[3])
			if (part == 0):
				if not Videostarted:
					start_time= time.time()
					print "Video stream started at frame", frame_n, datetime.datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S')
					print 'CTL-C to exit'
					Videostarted= 1
					if record_time:
						end_time= record_time * 60 + start_time
						print 'Recording will stop automatically at:', datetime.datetime.fromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')
				frame_prev= frame_n
				Video.write(outbuf)
				outbuf= ''
				dropping= False
				if end_time and time.time() >= end_time:
					print "Time's up!"
					os.kill(os.getpid(), signal.SIGINT)
			elif Videostarted:
				if not frame_prev == frame_n:
					print 'dropped frame', frame_n
					frame_prev= frame_n
					dropping= True
				if not part_prev + 1 == part:
					print 'dropped part %d of frame %d' % (part, frame_n)
					dropping= True
			if Videostarted and not dropping:
				outbuf += data[4:]
				Video_Bytes += len(data[4:])
			part_prev= part
    		keepalive()

