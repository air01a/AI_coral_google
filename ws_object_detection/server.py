
#!/usr/bin/env python3
 

TOKEN = ""
TIMER = 30

__all__ = ["SimpleHTTPRequestHandler"]
 
import os
import posixpath
import http.server
import urllib.request, urllib.parse, urllib.error
import cgi
import shutil
import mimetypes
import re
from io import BytesIO
import time 
import re
import picamera
import io

from edgetpu.detection.engine import DetectionEngine
from edgetpu.utils import dataset_utils
from PIL import Image
from PIL import ImageDraw


THRESHOLD = 0.5
picam = picamera.PiCamera()
engine = DetectionEngine('detect.tflite')
labels = dataset_utils.read_label_file('labelmap.txt')

def draw_objects(draw, objs, labels):
	for obj in objs:
		
		bbox = obj.bounding_box.flatten().tolist()

		draw.rectangle(bbox,
                                outline='red')
		draw.text((bbox[0] + 10, bbox[1] + 10),
                                '%s\n%.2f' % (labels[obj.label_id], obj.score),
                                fill='red')



class SimpleHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
	# check for security token
	def secure(self):
		global TOKEN
		self.cookie='?'
		headers = self.headers.get('Authorization')
		if  headers==None:
			print(str(self.path))
			if str(self.path).find(TOKEN)!=-1:
			   self.cookie='?id=' + TOKEN 
			   return True
		if headers == TOKEN:
			return True
        
		self.send_response(503)
		self.end_headers()
		return False

	#Manage GET
	def do_GET(self):
		if not self.secure():
			return False

		"""Serve a GET request."""
		f = self.send_head()
		if f:
			self.copyfile(f, self.wfile)
			f.close()
	
	# Manage HEAD
	def do_HEAD(self):
		if not self.secure():
			return False
		"""Serve a HEAD request."""
		f = self.send_head()
		if f:
			f.close()
 

	def capture(self):
		global picam
		self.send_response(200)
		picam.resolution=(640,480)
		picam.rotation=180
		picam.framerate=15
		self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=--jpgboundary')
		self.end_headers()
		my_stream = io.BytesIO()
		#try:
		for frameR in picam.capture_continuous(my_stream, format="jpeg", use_video_port=True):
			image = Image.open(frameR)
			boxes = engine.detect_with_image(
      					image,
      					threshold=THRESHOLD,
      					keep_aspect_ratio=1,
      					relative_coord=False,
      					top_k=10)

			draw_objects(ImageDraw.Draw(image), boxes, labels)
			httpstream = io.BytesIO()
			image.save(httpstream,'JPEG')
			self.wfile.write("--jpgboundary\r\n".encode())
			self.end_headers()
			self.wfile.write(bytearray(httpstream.getvalue()))
			my_stream.seek(0)
			my_stream.truncate()

#		except:
#			picam.close()

	# Send header to get and head request
	def send_head(self):
		path = self.translate_path(self.path)

		print("* %s" % path)
		if path.endswith("/capture.mjpg"):
			self.capture()
		f = None
		if os.path.isdir(path):
			if not self.path.endswith('/'):
				# redirect browser - doing basically what apache does
				self.send_response(301)
				self.send_header("Location", self.path + "/")
				self.end_headers()
				return None
			for index in "index.html", "index.htm":
				index = os.path.join(path, index)
				if os.path.exists(index):
					path = index
					break
			else:
				return self.list_directory(path)
		ctype = self.guess_type(path)
		try:
			f = open(path, 'rb')
		except IOError:
			self.send_error(404, "File not found")
			return None
		self.send_response(200)
		self.send_header("Content-type", ctype)
		fs = os.fstat(f.fileno())
		self.send_header("Content-Length", str(fs[6]))
		self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
		self.end_headers()
		return f
 
	def copyfile(self, source, outputfile):
		shutil.copyfileobj(source, outputfile)


	# List files in current directory and encapsulate the result in html
	def list_directory(self, path):	
		try:
			list = os.listdir(path)
		except os.error:
			self.send_error(404, "No permission to list directory")
			return None
		list.sort(key=lambda a: a.lower())
		f = BytesIO()
		displaypath = cgi.escape(urllib.parse.unquote(self.path))
		f.write(b'<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">')
		f.write(("<html>\n<title>Directory listing for %s</title>\n" % displaypath).encode())
		f.write(("<body>\n<h2>Directory listing for %s</h2>\n" % displaypath).encode())
		f.write(b"<hr>\n")
		f.write(b"<form ENCTYPE=\"multipart/form-data\" method=\"post\">")
		f.write(b"<input name=\"imageFile\" type=\"file\"/>")
		f.write(b"<input type=\"submit\" value=\"upload\"/></form>\n")
		f.write(b"<hr>\n<ul>\n")
		for name in list:
			fullname = os.path.join(path, name)
			displayname = linkname = name
			# Append / for directories or @ for symbolic links
			if os.path.isdir(fullname):
				displayname = name + "/"
				linkname = name + "/"
			if os.path.islink(fullname):
				displayname = name + "@"
				# Note: a link to a directory displays with @ and links with /
			f.write(('<li><a href="%s">%s</a>\n'
					% (urllib.parse.quote(linkname)+self.cookie, cgi.escape(displayname))).encode())
		f.write(b"</ul>\n<hr>\n</body>\n</html>\n")
		length = f.tell()
		f.seek(0)
		self.send_response(200)
		self.send_header("Content-type", "text/html")
		self.send_header("Content-Length", str(length))
		self.end_headers()
		return f
 
	def translate_path(self, path):
		# abandon query parameters
		path = path.split('?',1)[0]
		path = path.split('#',1)[0]
		path = posixpath.normpath(urllib.parse.unquote(path))
		words = path.split('/')
		words = [_f for _f in words if _f]
		path = os.getcwd()
		for word in words:
			drive, word = os.path.splitdrive(word)
			head, word = os.path.split(word)
			if word in (os.curdir, os.pardir): continue
			path = os.path.join(path, word)
		return path

	def guess_type(self, path):
		base, ext = posixpath.splitext(path)
		if ext in self.extensions_map:
			return self.extensions_map[ext]
		ext = ext.lower()
		if ext in self.extensions_map:
			return self.extensions_map[ext]
		else:
			return self.extensions_map['']
 
	if not mimetypes.inited:
		mimetypes.init() # try to read system mime.types
	extensions_map = mimetypes.types_map.copy()
	extensions_map.update({
		'': 'application/octet-stream', # Default
		'.py': 'text/plain',
		'.c': 'text/plain',
		'.h': 'text/plain',
		})
 
 
def run(HandlerClass = SimpleHTTPRequestHandler,ServerClass = http.server.HTTPServer):
	server_address = ('0.0.0.0', 8081)
	httpd = ServerClass(server_address,HandlerClass)
	httpd.serve_forever()
 
if __name__ == '__main__':
	run()
