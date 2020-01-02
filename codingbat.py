"""Downloads the https://codingbat.com/java problems as .py files"""
import asyncio
import os
import re
import typing

import aiohttp
import requests
from bs4 import BeautifulSoup


class ProcessingError(Exception):
    """Exception for when you try to write a file but it hasn't been processed yet
    Only used in CategoryPage.write
    """


class Converter:
    """Converts a problem declaration to a python one"""

    def __init__(self, dec):
        self.dec = dec[dec.index(' ') + 1:dec.index(')') + 1]

    def type_conversion(self, vartype):
        """Converts a java type to a Python type"""
        general_conversion = {
            'String': 'str',
            'Integer': 'int',
            'Map': 'Dict',
            'boolean': 'bool',
            'Boolean': 'bool'
        }
        if vartype.startswith('Map'):
            attrs = vartype[vartype.index('<') + 1:vartype.index('>')].split(', ')
            attrs = ', '.join([general_conversion[i] if i in general_conversion else i for i in attrs])
            return f'Dict[{attrs}]'
        if vartype.startswith('List'):
            try:
                attr = vartype[vartype.index('<') + 1:vartype.index('>')]
            except ValueError:
                return 'list'
            attr = general_conversion[attr] if attr in general_conversion else attr
            return f'List[{attr}]'
        if vartype.endswith('[]'):
            attr = general_conversion[vartype[:-2]] if vartype[:-2] in general_conversion else vartype[:-2]
            return f'List[{attr}]'
        return general_conversion[vartype] if vartype in general_conversion else vartype

    def handle_params(self, paramstr) -> typing.List[str]:
        """Handles the parameters of the declaration"""
        # splits parameters correctly if there's a Map
        lcarrot_count = 0
        rcarrot_count = 0
        split_idx = 0
        params = []
        for idx, i in enumerate(paramstr):
            if i == '<':
                lcarrot_count += 1
            elif i == '>':
                rcarrot_count += 1
            elif i == ',' and lcarrot_count == rcarrot_count or idx == len(paramstr) - 1:
                param = paramstr[split_idx:idx + (idx == len(paramstr) - 1)]
                paramtype, paramname = re.search(r'(.+) (\w+)$', param).groups()
                if paramname == 'str':
                    paramname = 'string'
                elif paramname == 'len':
                    paramname = 'length'
                elif paramname == 'map':
                    paramname = 'mapping'
                params.append(f'{paramname}: {self.type_conversion(paramtype)}')
                split_idx = idx + 2 #skips comma and space
        return params

    def convert(self):
        """Converts Java declaration to Python one"""
        namesearch = re.search(r'(\w+)\(', self.dec)
        rettype = self.type_conversion(self.dec[:namesearch.start()].strip())
        name = namesearch[1]
        paramstr = self.dec[self.dec.index('(') + 1:self.dec.index(')')]
        params = ', '.join(self.handle_params(paramstr))
        return f'def {name}({params}) -> {rettype}:\n    pass'


class Problem:
    """A page of a problem"""
    def __init__(self, url):
        self.url = url
        self.name = None
        self.text = None

    @staticmethod
    def make_asserts(asserts: typing.List[int]):
        """Makes assertions for the file"""
        conversions = {
            '→': '==',
            'true': 'True',
            'false': 'False'
        }
        asserts = [re.sub(r'→|true|false', lambda x: conversions[x[0]], i) for i in asserts]
        asserts = ''.join([f'\n    assert {i}' for i in asserts])
        return f"if __name__ == '__main__':{asserts}"

    def _process(self, response_text):
        """Processes file after requests have been made"""
        soup = BeautifulSoup(response_text, 'html.parser')
        self.name = soup.find_all('span', class_='h2')[-1].get_text()
        #making declaration
        decstr = soup.find('div', id='ace_div').get_text()
        decstr = Converter(decstr).convert()
        #making assertions
        asserts = soup.find_all(text=re.compile(r'→'))
        asserts = self.make_asserts(asserts)
        #making docstring
        docstring = soup.find('p', class_='max2').get_text().strip()
        docstringwrap = []
        idx1 = 0
        idx2 = 0
        lettercount = 0
        while idx2 < len(docstring):
            if lettercount > 81 and docstring[idx2] == ' ' or idx2 == len(docstring) - 1:
                docstringwrap.append(docstring[idx1:idx2 + (idx2 == len(docstring) - 1)])
                lettercount = 0
                idx1 = idx2 + 1
            idx2 += 1
            lettercount += 1
        docstring = '\"\"\"\n' + '\n'.join(docstringwrap) + '\n\"\"\"'
        #making imports
        imports = []
        if 'List' in decstr:
            imports.append('List')
        if 'Dict' in decstr:
            imports.append('Dict')
        if imports:
            imports = f'from typing import {", ".join(imports)}\n'
        else:
            imports = ''
        self.text = f'{docstring}\n{imports}\n\n{decstr}\n\n\n{asserts}\n'


    async def async_process(self, session: aiohttp.ClientSession):
        """Makes the text for the Python file asynchronously"""
        if self.text is not None:
            return None
        res = await session.get(self.url)
        restext = await res.text()
        self._process(restext)

    def process(self):
        """Makes the text for the Python file
        This function is basically just for debugging; the program runs async
        """
        if self.text is not None:
            return None
        res = requests.get(self.url)
        restext = res.text
        self._process(restext)

class CategoryPage:
    """A category that has all the problems in it"""
    def __init__(self, url):
        self.url = url
        self.name = re.search(r'/([\w\-]+)$', url)[1]
        self.problems = []
        self.processed = False

    async def process(self, session: aiohttp.ClientSession):
        """Processes the readme and processes all of the category's problems"""
        res = await session.get(self.url)
        restext = await res.text()
        soup = BeautifulSoup(restext, 'html.parser')
        problem_hrefs = soup.find_all('a', href=re.compile(r'/prob/'))
        self.problems = [Problem(f'https://codingbat.com{i["href"]}') for i in problem_hrefs]
        tasks = [asyncio.ensure_future(prob.async_process(session)) for prob in self.problems]
        await asyncio.gather(*tasks)
        self.processed = True

    def write(self):
        """Writes the files in the category
        Raises ProcessingException if self.processed is False
        """
        try:
            assert self.processed
        except AssertionError:
            raise ProcessingError(f'{self.name} has not been processed')
        for prob in self.problems:
            with open(os.path.join('.', self.name, f'{prob.name}.py'), 'w+', encoding='utf8') as f:
                f.write(prob.text)


async def main():
    """Main function
    Writes all the shit
    """
    mainpage = requests.get('https://codingbat.com/')
    soup = BeautifulSoup(mainpage.text, 'html.parser')
    categories_hrefs = soup.find_all('a', href=re.compile(r'/java/'))
    categories = [CategoryPage(f'https://codingbat.com{i["href"]}') for i in categories_hrefs]
    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.ensure_future(cat.process(session)) for cat in categories]
        await asyncio.gather(*tasks)
    for cat in categories:
        # In case the file has already been run
        if cat.name not in os.listdir():
            os.mkdir(cat.name)
        cat.write()
    print('Complete!')


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
