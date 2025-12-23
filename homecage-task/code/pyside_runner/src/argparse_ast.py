
# -*- coding: utf-8 -*-
# ASTベースで対象スクリプトの parse_args() を静的解析し、
# add_argument() 定義から引数情報を抽出してGUIに渡すための辞書リストへ変換する。
# 安全のためインポートや実行は行わない。

from __future__ import annotations
import ast
from typing import Any, Dict, List

ARG_TYPES = ['flag','str','int','float','list[int]','list[float]','list[str]']

def literal(node: ast.AST):
    """astノードをPython値へ（最小限）。定数・リスト・タプルのみ対応。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(literal(e) for e in node.elts)
    if isinstance(node, ast.List):
        return [literal(e) for e in node.elts]
    if hasattr(ast, 'NameConstant') and isinstance(node, getattr(ast, 'NameConstant')):
        return node.value
    return None

def choose_opt_name(opts: List[str]) -> str:
    """長いオプション（--long）を優先。なければ先頭。"""
    longs = [o for o in opts if isinstance(o, str) and o.startswith('--')]
    return longs[0] if longs else (opts[0] if opts else '')

def _default_for_type(t: str):
    if t == 'int':
        return 0
    if t == 'float':
        return 0.0
    if t.startswith('list'):
        return []
    if t == 'flag':
        return False
    return ''

def _type_from_typobj(typobj: Any) -> str:
    if typobj is int:
        return 'int'
    if typobj is float:
        return 'float'
    return 'str'

def _apply_nargs(base_type: str, nargs: Any) -> str:
    if isinstance(nargs, int) and nargs >= 2:
        if base_type == 'int':
            return 'list[int]'
        if base_type == 'float':
            return 'list[float]'
        return 'list[str]'
    if isinstance(nargs, str) and nargs in ('+','*'):
        if base_type == 'int':
            return 'list[int]'
        if base_type == 'float':
            return 'list[float]'
        return 'list[str]'
    return base_type

def extract_args_from_source(source: str) -> List[Dict[str, Any]]:
    """
    `def parse_args():` を探索し、その中の ArgumentParser 変数に対する
    add_argument 呼び出しを抽出して辞書リストを返す。
    戻り値: [{'enabled': True, 'name': str, 'type': str, 'value': Any}, ...]
    """
    tree = ast.parse(source)

    # parse_args 関数を特定
    parse_fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'parse_args':
            parse_fn = node
            break
    if parse_fn is None:
        return []

    # 関数内の ArgumentParser 変数名を抽出（例: p）
    parser_vars = set()
    for node in ast.walk(parse_fn):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            cal = node.value
            if isinstance(cal.func, ast.Attribute) and isinstance(cal.func.value, ast.Name):
                if cal.func.value.id == 'argparse' and cal.func.attr == 'ArgumentParser':
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            parser_vars.add(tgt.id)

    if not parser_vars:
        return []

    rows: List[Dict[str, Any]] = []

    for node in ast.walk(parse_fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            recv = node.func.value
            method = node.func.attr
            if method != 'add_argument':
                continue
            if not (isinstance(recv, ast.Name) and recv.id in parser_vars):
                continue

            # 位置引数（名前）
            names: List[str] = []
            for a in node.args:
                val = literal(a)
                if isinstance(a, ast.Constant) and isinstance(val, str):
                    names.append(val)

            # キーワード引数
            kwargs = {kw.arg: literal(kw.value) for kw in node.keywords}
            action = kwargs.get('action')
            typobj = kwargs.get('type')
            nargs = kwargs.get('nargs')
            default = kwargs.get('default')
            required = kwargs.get('required')

            if names and names[0].startswith('-'):
                # オプション
                name = choose_opt_name(names)
                if action in ('store_true','store_false'):
                    rows.append({
                        'enabled': True,
                        'name': name,
                        'type': 'flag',
                        'value': bool(default) if default is not None else (action == 'store_true'),
                    })
                else:
                    base_t = _type_from_typobj(typobj)
                    t = _apply_nargs(base_t, nargs)
                    val = default if default is not None else _default_for_type(t)
                    rows.append({
                        'enabled': True,
                        'name': name,
                        'type': t,
                        'value': val,
                    })
            else:
                # 位置引数
                name = names[0] if names else ''
                base_t = _type_from_typobj(typobj)
                t = _apply_nargs(base_t, nargs)
                val = default if default is not None else _default_for_type(t)
                rows.append({
                    'enabled': True,
                    'name': name,
                    'type': t,
                    'value': val,
                })

    # 重複除去（名前+型で一意）
    uniq, seen = [], set()
    for r in rows:
        key = (r.get('name'), r.get('type'))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    return uniq

