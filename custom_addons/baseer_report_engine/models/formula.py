"""Arithmetic over report line codes. No eval and no names from outside the formula."""

import re
from decimal import Decimal


class FormulaError(Exception):
    def __init__(self, code, detail=None):
        super().__init__(code)
        self.code = code
        self.detail = detail


_NAME = re.compile(r'^[A-Z][A-Z0-9_]*$')


def tokenize(formula):
    tokens = []
    index = 0
    length = len(formula or '')
    while index < length:
        char = formula[index]
        if char.isspace():
            index += 1
            continue
        if char in '+-*/()':
            tokens.append(('op', char))
            index += 1
            continue
        if char.isalpha() or char == '_':
            start = index
            index += 1
            while index < length and (formula[index].isalnum() or formula[index] == '_'):
                index += 1
            name = formula[start:index]
            if not _NAME.match(name):
                raise FormulaError('syntax')
            tokens.append(('name', name))
            continue
        if char.isdigit():
            start = index
            index += 1
            while index < length and formula[index].isdigit():
                index += 1
            if index < length and formula[index] == '.':
                index += 1
                if index >= length or not formula[index].isdigit():
                    raise FormulaError('syntax')
                while index < length and formula[index].isdigit():
                    index += 1
            tokens.append(('num', Decimal(formula[start:index])))
            continue
        raise FormulaError('syntax')
    return tokens


def referenced_codes(formula):
    return [token[1] for token in tokenize(formula) if token[0] == 'name']


def evaluate_formula(formula, variables):
    tokens = tokenize(formula)
    if not tokens:
        raise FormulaError('syntax')
    index = 0

    def peek():
        return tokens[index] if index < len(tokens) else None

    def eat(kind=None, value=None):
        nonlocal index
        token = peek()
        if token is None or (kind and token[0] != kind) or (value is not None and token[1] != value):
            raise FormulaError('syntax')
        index += 1
        return token

    def parse_expression():
        node = parse_term()
        while peek() and peek()[0] == 'op' and peek()[1] in '+-':
            operator = eat()[1]
            node = ('bin', operator, node, parse_term())
        return node

    def parse_term():
        node = parse_factor()
        while peek() and peek()[0] == 'op' and peek()[1] in '*/':
            operator = eat()[1]
            node = ('bin', operator, node, parse_factor())
        return node

    def parse_factor():
        token = peek()
        if token and token == ('op', '-'):
            eat()
            return ('neg', parse_factor())
        if token and token == ('op', '('):
            eat()
            node = parse_expression()
            eat('op', ')')
            return node
        if token and token[0] == 'num':
            return ('num', eat()[1])
        if token and token[0] == 'name':
            return ('name', eat()[1])
        raise FormulaError('syntax')

    tree = parse_expression()
    if peek() is not None:
        raise FormulaError('syntax')
    return _eval(tree, variables)


def _eval(node, variables):
    kind = node[0]
    if kind == 'num':
        return node[1]
    if kind == 'name':
        if node[1] not in variables:
            raise FormulaError('unknown', node[1])
        return variables[node[1]]
    if kind == 'neg':
        return -_eval(node[1], variables)
    left = _eval(node[2], variables)
    right = _eval(node[3], variables)
    operator = node[1]
    if operator == '+':
        return left + right
    if operator == '-':
        return left - right
    if operator == '*':
        return left * right
    if right == 0:
        raise FormulaError('division')
    return left / right
