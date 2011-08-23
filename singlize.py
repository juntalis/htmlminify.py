#/usr/bin/env python
from pyquery import PyQuery as pq
import closure as js
import htmlminifier as html
import cssmin as css
from os import path, getcwd
import sys, re, mimetypes, base64


__author__ = 'Charles Grunwald <cgrunwald@gmail.com>'
__root__ = getcwd()

def data_encode_image(name,content):
	return u'data:%s;base64,%s' % (mimetypes.guess_type(name)[0],base64.standard_b64encode(content))

def resolve_url(filedir, url):
	if url[0:1] == '/':
		url = path.join(__root__, url[1:])
	else:
		url = path.join(filedir, str(url).replace('/', path.sep))
	url = path.abspath(url)
	return url

def inline(element):
	"""
	Get inline content to js or css
	"""
	return pq(element).text()

def process_js(filedir, scripts):
	if not len(scripts): return None
	result = ''
	for script in scripts:
		src = script.get('src')
		if src is None or len(src) == 0:
			print 'Found inline-script. Processing..'
			result += inline(script)
		else:
			match = re.search("^((?:file://)|(?:https?://)|(?:chrome://))", src)
			if match:
				print 'Script Url: %s' % src
				print 'Remote/URL-based resources not yet implemented.'
			else:
				print 'Found linked script. Resolving..'
				url = resolve_url(filedir, src)
				if not path.exists(url):
					print 'Script %s (resolved from %s) did not exist. Skipping..' % (url, src)
				else:
					print 'Script: %s' % url
					result += open(url).read()
	if not len(result): return None
	options = js.Options()
	options['jscode'] = result
	options['level'] = js.levelCoerce('simple')
	options['info'] = js.infoCoerce('compiled_code')
	result = js.compile(options)
	result = result.strip('\r\n \t')
	if not len(result): return None
	return result

__target_stylesheets__ = []

def process_css_internals(basedir, filedir, content):
	data = content
	if re.search(r"url\(", data, re.IGNORECASE):
		for match in re.finditer(r"""(?i)url\(['"]?([^)'"]+)['"]?\)""", data):
			urlMatch = match.group(1)
			if re.match(r"""url\(['"]?(?:[^)'"]+\.css)['"]?\)\Z""", urlMatch, re.IGNORECASE):
				# Imported CSS stylesheet.
				url = resolve_url(filedir, urlMatch)
				if basedir != filedir:
					url = path.relpath(url, basedir)
				print 'Need to import %s' % url
				#__target_stylesheets__.append({'href':})
			else:
				# Image
				url = resolve_url(filedir, urlMatch)
				#replacement = u'url(%s)' % data_encode_image(path, open(url, 'rb').read())
				data =  data_encode_image(url, open(url, 'rb').read())
				content = content.replace(urlMatch, data)

	#__target_stylesheets__
	return content


def process_css(filedir, styles, links):
	processed = []
	__target_stylesheets__.extend(links)
	result = ''
	if len(links) > 0:
		current = 0
		while current < len(__target_stylesheets__):
			link = __target_stylesheets__[current].get('href')
			if not len(link): continue
			match = re.search("^((?:file://)|(?:https?://)|(?:chrome://))", link)
			if match:
				print 'Stylesheet Url: %s' % link
				print 'Remote/URL-based resources not yet implemented.'
			else:
				print 'Found linked script. Resolving..'
				url = resolve_url(filedir, link)
				if not path.exists(url):
					print 'Stylesheet %s (resolved from %s) did not exist. Skipping..' % (url, link)
				else:
					if not url in processed:
						print 'Adding stylesheet: %s' % url
						contents = open(url).read()
						result += process_css_internals(filedir, path.abspath(path.dirname(url)), contents)
						processed.append(url)
					else:
						print '%s already processed.. Skipping.'
			current += 1
	if len(styles) > 0:
		for style in styles:
			print 'Found inline-style. Processing..'
			result += process_css_internals(filedir, filedir, inline(style))


	result = str(re.sub('[\r\n]', "", result)).strip()
	if not len(result): return None
	return css.cssmin(result)

def main(argv=None):
	if argv is None:
		argv = sys.argv

	if len(argv) != 3:
		print 'Usage: %s file.html output.html\n' % argv[0]
		exit(1)

	target = path.abspath(argv[1])
	if not path.exists(target):
		print '%s does not exist.' % target
		exit(1)

	output = path.abspath(argv[2])

	# Get directory of file, then read it into pyquery.
	filedir = path.abspath(path.dirname(target))
	content = open(target).read()
	d = pq(content)

	# Get all scripts and stylesheets
	scripts = d('script')
	links = d('link[rel="stylesheet"]')
	styles = d('style')

	# Process all assets.
	scripts = process_js(filedir, scripts)
	styles = process_css(filedir, styles, links)
	content = re.sub(r'(?si)(?:(?:<script[^>]*>).*?(?:</script>))|(?:(?:<style[^>]*>).*?(?:</style>))|(?:<link [^>]*rel="?stylesheet"?[^>]*/\s*?>)', "", content)
	if scripts is not None:
		scripts = '<script type="text/javascript" language="javascript">%s</script></body>\n' % scripts
		content = content.replace('</body>', scripts)
	if styles is not None:
		styles = '<style type="text/css">%s</style></head>' % styles
		content = content.replace('</head>', styles)
	print 'Minimizing HTML..'
	content = html.HtmlMinifier(value=content).minified
	f = open(output, 'w')
	f.write(content)
	f.close()

if __name__ == '__main__':
	main()