#!/usr/bin/env python
# HTMLMinifier.py v0.2
#
# Python reimplementation of:
# HTMLMinifier.py v0.43
# http://kangax.github.com/html-minifier/
#
# Copyright (c) 2010 Juriy "kangax" Zaytsev
# Licensed under the MIT license.

import re
from lxml import etree

class HtmlMinifier:

	# Our options
	opts = {
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
	}

	# The results of our minification.
	__results = []
	__buffer = []
	__stackNoTrimWhitespace = []
	__stackNoCollapseWhitespace = []
	__currentChars = ''
	__currentTag = ''

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

	def __init__(self, value=None, options=None):
		"""
		Constructor. If value is specified, we will
		immediately minimify it.
		"""
		if options is not None:
			self.opts = dict(self.opts, options)

		# If value is set, let's start it up.
		if value is not None and len(value) > 0:
			self.minified = self.minify(value)

	def __trimWhitespace(self, val):
		return val.strip('\n\r\t ')

	def __collapseWhitespace(self, str):
		return re.sub(r"\s+", " ", str)

	def __isConditionalComment(self, text):
		return True if re.match(r"\[if[^\]]+\]\Z", text) else False

	def __isEventAttribute(self, name):
		return re.match(r"^on[a-z]+\Z", name)

	def __canRemoveAttributeQuotes(self, val):
		return True if re.match("^[a-zA-Z0-9-._:]+$", val) else False

	def __attributesInclude(self, attrs, check):
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
		return True if re.match(r"(?:^(?:checked|disabled|selected|readonly)$)\Z", name) else False

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
		return True if not re.match(r"(?:^(?:script|style|pre|textarea)$)\Z", tag) else False

	def __canTrimWhitespace(self, tag):
		return True if not re.match(r"(?:^(?:pre|textarea)$)\Z", tag) else False

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

	def start(self, tag, attrs):
		"""
		Deal with a starting tag.
		"""
		tag = tag.lower()
		self.__currentTag = tag
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

#	def __unaryElement(self, tag, attrs):
#		print tag
#
	def end(self, tag):
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
		if self.__currentTag == 'script' or self.__currentTag == 'style':
			if self.opts['removeCommentsFromCDATA']:
				text = self.__removeComments(text, self.__currentTag)
			if self.opts['removeCDATASectionsFromCDATA']:
				text = self.__removeCDATASections(text)
		if self.opts['collapseWhitespace']:
			if not len(self.__stackNoTrimWhitespace) and self.__canTrimWhitespace(self.__currentTag):
				text = self.__trimWhitespace(text)
			if not len(self.__stackNoCollapseWhitespace) and self.__canCollapseWhitespace(self.__currentTag):
				text = self.__collapseWhitespace(text)

		self.__currentChars = text
		self.__buffer.append(text)

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

	def minify(self, value, options=None):
		# Set the new options.
		if options is not None: self.opts = dict(self.opts, options)

		# Verify value
		if value is None or len(value) == 0:
			raise Exception('Invalid value specified for minification. Must be a string larger than 0 characters.')

		# Reset the buffers.
		self.__buffer = []
		self.__stackNoTrimWhitespace = []
		self.__stackNoCollapseWhitespace = []
		self.__currentChars = ''
		self.__currentTag = ''

		# Until I can figure out how to access the actual doctype string when
		# using a custom parser..
		self.__doctype('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">')
		p = etree.HTMLParser(target = self)
		tree = etree.fromstring(value,parser=p)

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
		results = "".join(results)
		return results

if __name__ == '__main__':
	from sys import argv
	if len(argv) > 1:
		min = HtmlMinifier(value=open(argv[1]).read())
		if len(argv) == 3:
			open(argv[2],'w').write(min.minified)
		else:
			print min.minified
	else:
		print 'Usage: %s input [output]' % argv[0]

