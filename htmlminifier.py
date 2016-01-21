#!/usr/bin/env python
# encoding: utf-8
"""
HTMLMinifier.py v0.3

Python reimplementation of:
HTMLMinifier.py v0.43
http://kangax.github.com/html-minifier/

TODO: Not sure why I thought I needed to use the same names/naming
style as the original js code, but that was a really dumb decision.

This program is free software. It comes without any warranty, to
the extent permitted by applicable law. You can redistribute it
and/or modify it under the terms of the Do What The Fuck You Want
To Public License, Version 2, as published by Sam Hocevar. See
http://sam.zoy.org/wtfpl/COPYING for more details.
"""
import re, warnings
from lxml import etree
from httplib import HTTPConnection
from urllib import urlencode, getproxies, URLopener 

try:
	import jsmin
except ImportError:
	jsmin = None
	
	def jsmin_warning():
		warnings.warn("""
JS minification is attempted using the jsmin module, which is
currently missing from your Python environment. As a result,
minification will be attempted with the online Closure Compiler
webservice. Should that attempt fail, (which it may - for many
reasons) the JS will be left in its original form. It is 
advised that you install this dependency if you want to use
the functionality. (https://pypi.python.org/pypi/jsmin)
""")

try:
	import cssmin
except ImportError:
	cssmin = None
	
	def cssmin_warning():
		warnings.warn("""
CSS minification depends on the cssmin module, which is currently
missing from your Python environment. This option will be disabled
for the current minification.

Module URL: https://github.com/zacharyvoase/cssmin
""")

class HtmlMinifier(object):

	# Our options
	DEFAULT_OPTIONS = {
		'removeComments' : True,
		'removeCommentsFromCDATA' : True,
		'removeCDATASectionsFromCDATA' : True,
		'collapseWhitespace' : True,
		'collapseBooleanAttributes' : True,
		'removeAttributeQuotes' : True,
		'removeRedundantAttributes' : True,
		'useShortDoctype' : True,
		'removeEmptyAttributes' : True,
		'removeOptionalTags' : True,
		'removeEmptyElements' : False,
		'removeScriptTypeAttributes' : False,
		'removeStyleLinkTypeAttributes' : False,
		'minifyJS': True,
		'minifyCSS': True,
	}

	# The results of our minification.
	__results = []
	__buffer = []
	__stackNoTrimWhitespace = []
	__stackNoCollapseWhitespace = []
	__currentChars = ''
	__currentTag = ''
	__opener = None
	
	# Cached regex instances
	reBlank = re.compile(r"^\s*$")
	
	# account for js + html comments (e.g.: //<!--)
	__reStartDelimiter = {
		'script' : re.compile(r"^\s*?(?://)?\s*?<!--.*?\n?"),
		'style'  : re.compile(r"^\s*?<!--\s*?")
	}
	__reEndDelimiter = {
		'script' : re.compile(r"\s*?(?://)?\s*?-->\s*?$"),
		'style'  : re.compile(r"\s*?-->\s*?$")
	}

	# Possible empty attributes to remove.
	__reEmptyAttribute = re.compile(
		"^(?:class|id|style|title|lang|dir|on(?:focus|blur|change|click|dblclick|mouse(' + '?:down|up|over|move|out)|key(?:press|down|up)))$"
	)

	def __init__(self, htmltext=None, options=None):
		"""
		Constructor. If htmltext is specified, we will
		immediately minify it.
		"""
		self.opts = HtmlMinifier.DEFAULT_OPTIONS.copy()
		if options is not None:
			self.opts.update(options)

		# Check for the js module when minifyJS is
		# specified. Issue a warning if it's missing.
		if self.opts['minifyJS'] and jsmin is None:
			jsmin_warning()
		
		# Check for the cssmin module when minifyCSS is
		# specified. Issue a warning and disable the option
		# if it cannot be found.
		if self.opts['minifyCSS'] and cssmin is None:
			self.opts['minifyCSS'] = False
			cssmin_warning()
		
		# If htmltext is set, let's start it up.
		if htmltext is not None and len(htmltext) > 0:
			self.minified = self.minify(htmltext)

	def __trimWhitespace(self, val):
		""" Why the hell did I make this  a method? Typing
		self.__trimWhitespace(text) takes more characters
		to write than text.strip() """
		return val.strip()

	def __collapseWhitespace(self, str):
		return re.sub(r"\s{2,}", " ", str)

	def __isConditionalComment(self, text):
		return bool(re.match(r"\[if[^\]]+\]\Z", text))

	def __isEventAttribute(self, name):
		return bool(re.match(r"^on[a-z]+\Z", name))

	def __canRemoveAttributeQuotes(self, val):
		return bool(re.match("^[a-zA-Z0-9-._:]+$", val))

	def __attributesInclude(self, attrs, check):
		""" TODO: Check if whatever's used for attribute collections
		is case-sensitive when it comes to attribute names. Repeatedly
		iterating the attribute set for every attribute is awful. """
		for attr in attrs:
			if attr.name.lower() == check:
				return True
		return False

	def __isAttributeRedundant(self, tag, name, val, attrs):
		val = self.__trimWhitespace(val.lower())
		return	(tag=='script' and name=='language' and val=='javascript') or\
				(tag=='form' and name=='method' and val=='get') or\
				(tag=='input' and name=='type' and val=='text') or\
				(tag=='script' and name=='charset' and not self.__attributesInclude(attrs, 'src')) or\
				(tag=='a' and name=='name' and self.__attributesInclude(attrs, 'id')) or\
				(tag=='area' and name=='shape' and val=='rect')

	def __isScriptTypeAttribute(self, tag, name, val):
		return tag=='script' and name=='type' and self.__trimWhitespace(val.lower())=='text/javascript'

	def __isStyleLinkTypeAttribute(self, tag, name, val):
		val = self.__trimWhitespace(val.lower())
		return (tag=='style' or tag=='link') and name=='type' and val=='text/css'

	def __isBooleanAttribute(self, name):
		return bool(re.match(r"(?:^(?:checked|disabled|selected|readonly)$)\Z", name))

	def __isUriTypeAttribute(self, name, tag):
		return	(re.match(r"(?:^(?:a|area|link|base)$)\Z", tag) and name=='href') or\
				(tag=='img' and re.match(r"(?:^(?:src|longdesc|usemap)$)\Z", name)) or\
				(tag=='object' and re.match(r"(?:^(?:classid|codebase|data|usemap)$)\Z", name)) or\
				(tag=='q' and name=='cite') or (tag=='blockquote' and name=='cite') or\
				((tag=='ins' or tag=='del') and name=='cite') or (tag=='form' and name=='action') or\
				(tag=='input' and (name=='src' or name=='usemap')) or (tag=='head' and name=='profile') or\
				(tag=='script' and (name=='src' or name=='for'))

	def __isNumberTypeAttribute(self, name, tag):
		return	(re.match(r"(?:^(?:a|area|object|button)$)\Z", tag) and name=='tabindex') or\
				(tag=='input' and (name=='maxlength' or name=='tabindex')) or\
				(tag=='select' and (name=='size' or name=='tabindex')) or\
				(tag=='textarea' and re.match(r"(?:^(?:rows|cols|tabindex)$)\Z", name)) or\
				(tag=='colgroup' and name=='span') or (tag=='col' and name=='span') or\
				(tag=='th' or tag=='td' and name=='rowspan' or name=='colspan')

	def __cleanAttributeValue(self, tag, name, val):
		if self.__isEventAttribute(name):
			return re.sub(r"\s*;$", "", re.sub(r"^javascript:\s*", "", self.__trimWhitespace(val)))
		elif name=='class':
			return self.__collapseWhitespace(self.__trimWhitespace(val))
		elif self.__isUriTypeAttribute(name, tag) or self.__isNumberTypeAttribute(name, tag):
			return self.__trimWhitespace(val)
		elif name=='style':
			return re.sub(r"\s*;\s*$", "", self.__trimWhitespace(val))
		return val

	def __cleanConditionalComment(self, comment):
		return re.sub(r"\s*(<!\[endif\])$", "$1", re.sub(r"^(\[[^\]]+\]>)\s*", "$1", comment))

	def __removeCDATASections(self, text):
		return re.sub(r"(?:/\*\s*\]\]>\s*\*/|//\s*\]\]>)\s*$", "", re.sub(r"^(?:\s*/\*\s*<!\[CDATA\[\s*\*/|\s*//\s*<!\[CDATA\[.*)", "", text))

	def __removeComments(self, text, tag):
		return self.__reEndDelimiter[tag].sub("", self.__reStartDelimiter[tag].sub("", text))

	def __isOptionalTag(self, tag):
		return re.match(r"(?:^(?:tbody|thead|tfoot|tr|option)$)\Z", tag)

	def __canDeleteEmptyAttribute(self, tag, name, val):
		"""
		http://www.w3.org/TR/html4/intro/sgmltut.html#attributes
		avoid \w, which could match unicode in some implementations
		"""
		isValEmpty = re.match(r"""^(["'])?\s*\1$""", val)
		if isValEmpty:
			return (tag == 'input' and name == 'value') or self.__reEmptyAttribute.match(name)
		return False

	def __canRemoveElement(self, tag):
		return tag != 'textarea'

	def __canCollapseWhitespace(self, tag):
		return bool(not re.match(r"(?:^(?:script|style|pre|textarea)$)\Z", tag))

	def __canTrimWhitespace(self, tag):
		return bool(not re.match(r"(?:^(?:pre|textarea)$)\Z", tag))

	def __normalizeAttribute(self, curr, attrs, tag):
		# Store the name and value of the attribute
		(name, val) = (curr.lower(), attrs[curr])
		val = '' if val is None else val

		if (self.opts['removeRedundantAttributes'] and self.__isAttributeRedundant(tag,name,val,attrs)) or \
		   (self.opts['removeScriptTypeAttributes'] and self.__isScriptTypeAttribute(tag,name,val)) or \
		   (self.opts['removeStyleLinkTypeAttributes'] and self.__isStyleLinkTypeAttribute(tag,name,val)):
			return ''

		val = self.__cleanAttributeValue(tag, name, val)
		if not self.opts['removeAttributeQuotes'] or not self.__canRemoveAttributeQuotes(val):
			val = '"' + val + '"'

		if self.opts['removeEmptyAttributes'] and self.__canDeleteEmptyAttribute(tag, name, val):
			return ''

		if self.opts['collapseBooleanAttributes'] and self.__isBooleanAttribute(name):
			frag = name
		else:
			frag = name + '=' + val
		return ' ' + frag

	@staticmethod
	def read_asset(self, url):
		""" Open using a lazy initialized URLopener instance.
		TODO: URLopener is apparently flakey. Need to change to urllib2 or 
		something more stable. """
		if HtmlMinifier.__opener is None:
			HtmlMinifier.__opener = URLopener()
			HtmlMinifier.__opener.addheader('Accept', '*/*')
		
		# Can't use a with statement with URLopener stuff. ):
		cssfile = HtmlMinifier.__opener.open(url)
		csscode = cssfile.read()
		cssfile.close()
		return csscode

	@staticmethod
	def cssmin(css_code=None, css_url=None):
		""" Pretty much just a pass-through to cssmin.cssmin """
		if css_url is not None:
			css_code = HtmlMinifier.read_asset(css_url)
		elif css_code is None:
			raise ValueError('Must specify a value for either css_code or css_url')
		return cssmin.cssmin(css_code)

	@staticmethod
	def jsmin(js_code=None, js_url=None):
		""" Compile js_code using the jsmin module. If it'seek
		missing, fall back on the Google Closure Compiler service
		found at http://closure-compiler.appspot.com If that fails,
		just leave the javascript as is. """
		use_jsmin = jsmin is not None
		
		# Param presets for the Closure Compiler Service
		params = [
			('output_format', 'text'),
			('output_info', 'compiled_code'),
			('compilation_level', 'SIMPLE_OPTIMIZATIONS'),
		]
		
		# Figure out if we're using a url or the js source itself
		if js_url is not None:
			if use_jsmin:
				js_code = HtmlMinifier.read_asset(js_url)
			else:
				params.append(('code_url', js_url))
		elif js_code is None:
			raise ValueError('Must specify a value for either js_code or js_url')
		else:
			# Unused if we go the jsmin route but oh well.
			params.append(('js_code', js_code))
		
		# Use jsmin if we got it. Otherwise
		if use_jsmin:
			return jsmin.jsmin(js_code)
		
		# Always use the following headers
		headers = {
			'Accept': 'text/javascript,*/*',
			#'Accept-Encoding': 'gzip, deflate',
			'Referer': 'http://closure-compiler.appspot.com/home',
			'Content-type': 'application/x-www-form-urlencoded;charset=utf-8',
			'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:43.0) Gecko/20100101 Firefox/43.0',
		}
		
		connection = HTTPConnection('closure-compiler.appspot.com')
		connection.request('POST', '/compile', urlencode(params), headers)
		response = connection.getresponse()
		data = response.read()
		connection.close()
		
		# The Closure Compiler services uses a successful status code
		# even when it errors out, so we need to check if the body
		# contains text and doesn't contain an error message.
		if data.startswith('Error(') or HtmlMinifier.reBlank.match(data):
			if js_code is None:
				js_code = HtmlMinifier.read_asset(js_url)
			data = js_code
		
		return data

	def _handle_cdata(self, text):
		""" Common handling for inline scripts and styles. """
		if self.opts['removeCommentsFromCDATA']:
			text = self.__removeComments(text, self.__currentTag)
		if self.opts['removeCDATASectionsFromCDATA']:
			text = self.__removeCDATASections(text)
		return text
	
	def start(self, tag, attrs):
		"""
		Deal with a starting tag.
		"""
		tag = tag.lower()
		self.__currentTag = tag
		self.__currentAttrs = attrs
		self.__currentChars = ''

		# White space management
		if self.opts['collapseWhitespace']:
			#tag = tag.lower()
			if not self.__canTrimWhitespace(tag):
				self.__stackNoTrimWhitespace.append(tag)
			if not self.__canCollapseWhitespace(tag):
				self.__stackNoCollapseWhitespace.append(tag)

		# Add to buffer
		self.__buffer.append('<')
		self.__buffer.append(tag)
		for attr in attrs:
			self.__buffer.append(self.__normalizeAttribute(attr, attrs, tag))
		self.__buffer.append('>')

	def end(self, tag):
		# Process all of the collected text data
		text = self.__currentChars
		if self.__currentTag == 'script':
			text = self._handle_cdata(text)
			if self.opts['minifyJS'] and not HtmlMinifier.reBlank.match(text):
				if self.__currentAttrs is None or not ('src' in self.__currentAttrs):
					text = HtmlMinifier.jsmin(text)
		elif self.__currentTag == 'style':
			text = self._handle_cdata(text)
			if self.opts['minifyCSS'] and not HtmlMinifier.reBlank.match(text):
				text = HtmlMinifier.cssmin(text)
		
		self.__currentChars = text
		self.__buffer.append(text)
		
		if self.opts['collapseWhitespace']:
			if len(self.__stackNoTrimWhitespace) and tag == self.__stackNoTrimWhitespace[len(self.__stackNoTrimWhitespace) - 1]:
				self.__stackNoTrimWhitespace.pop()

			if len(self.__stackNoCollapseWhitespace) and tag == self.__stackNoCollapseWhitespace[len(self.__stackNoCollapseWhitespace) - 1]:
				self.__stackNoCollapseWhitespace.pop()

		isElementEmpty = self.__currentChars == '' and tag == self.__currentTag
		if self.opts['removeEmptyElements'] and isElementEmpty and self.__canRemoveElement(tag):
			self.__buffer.reverse()
			lastIndexOf = len(self.__buffer) -1 - self.__buffer.index('<')
			self.__buffer.reverse()
			self.__buffer = self.__buffer[lastIndexOf:]
			return
		elif self.opts['removeOptionalTags'] and self.__isOptionalTag(tag):
			return
		else:
			self.__buffer.append('</')
			self.__buffer.append(tag.lower())
			self.__buffer.append('>')
			for c in self.__buffer: self.__results.append(c)
			#self.__results.extend(self.__buffer)

		self.__buffer = []
		self.__currentChars = ''

	def data(self, text):
		""" Process an element's inner text """
		if text is None: return
		if self.opts['collapseWhitespace']:
			if not len(self.__stackNoTrimWhitespace) and self.__canTrimWhitespace(self.__currentTag):
				text = self.__trimWhitespace(text)
			if not len(self.__stackNoCollapseWhitespace) and self.__canCollapseWhitespace(self.__currentTag):
				text = self.__collapseWhitespace(text)

		self.__currentChars += text

	def comment(self, text):
		if self.opts['removeComments']:
			if self.__isConditionalComment(text):
				text = '<not --' + self.__cleanConditionalComment(text) + '-->'
			else:
				text = ''
		else:
			text = '<not --' + text + '-->'
		self.__buffer.append(text)

	def __doctype(self, doctype):
		self.__buffer.append('<!DOCTYPE html>' if self.opts['useShortDoctype'] else self.__collapseWhitespace(doctype))

	def __cref(self, name):
		self.__buffer.append('&#' + name + ';')

	def __eref(self, name):
		self.__buffer.append('&' + name + ';')

	def close(self):
		return ''

	def minify(self, htmltext, options=None):
		# Set the new options.
		if options is not None: self.opts = dict(self.opts, options)

		# Verify htmltext
		if htmltext is None or len(htmltext) == 0:
			raise ValueError('Invalid value specified for parameter: htmltext. Must be a string larger than 0 characters.')

		# Reset the buffers.
		self.__buffer = []
		self.__stackNoTrimWhitespace = []
		self.__stackNoCollapseWhitespace = []
		self.__currentChars = ''
		self.__currentTag = ''
		self.__currentAttrs = None

		# Until I can figure out how to access the actual doctype string when
		# using a custom parser..
		self.__doctype('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">')
		p = etree.HTMLParser(target = self)
		tree = etree.fromstring(htmltext, parser=p)

		# Iterate and add buffer to results.
		for c in self.__buffer: self.__results.append(c)
		self.__buffer = []

		# Trim the remainder of the results.
		results = []
		for c in self.__results:
			if re.search(r"[^\s\r\n]", c):
				if re.search(r"^(?:[\s\r\n]+([\s]))", c):
					c = re.sub(r"^(?:[\s\r\n]+([\s]))", r"\1", c)
				if re.search(r"(?:([\s])[\s\r\n]+)$", c):
					c = re.sub(r"(?:([\s])[\s\r\n]+)$", r"\1", c)
			else:
				if len(c) > 0:
					c = c[0]
			if len(c) > 0:
				results.append(c)
		results = ''.join(results)
		return results

if __name__ == '__main__':
	import sys
	
	if len(sys.argv) > 1:
		# Read input
		htmlfile = open(sys.argv[1], 'rt')
		htmlcode = htmlfile.read()
		htmlfile.close()
		
		# Minify code
		htmlmin = HtmlMinifier(htmlcode)
		
		# Figure out the output
		outfile = None
		if len(sys.argv) > 2:
			outfile = open(sys.argv[2], 'w')
		else:
			outfile = sys.stdout
		
		# Write contents and close
		outfile.write(htmlmin.minified)
		outfile.close()
	else:
		print 'Usage: %s input [output]' % sys.argv[0]
