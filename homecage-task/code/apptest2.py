
# app.py
# -*- coding: utf-8 -*-
"""
PySide6 で Python スクリプトのランチャーを作るテンプレート
- 指定フォルダから .py を列挙して選択
- コマンドライン引数を表で編集（有効/名前/型/値）
- 非同期実行(QProcess)で標準出力・標準エラーを表示
- スクリプトごとの引数プリセットを保存/読み込み
"""

import sys
from pathlib import Path
from typing import List, Dict, Any

from PySide6.QtCore import Qt, QProcess, QStandardPaths
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget,
    QTableWidgetItem, QCheckBox, QPlainTextEdit, QSpinBox, QDoubleSpinBox
)
from PySide6.QtGui import QAction

import ast
import re


APP_NAME = "PyScriptRunner"
ORG_NAME = "EtoHayato"  # QSettingsの識別用（任意）

# 引数タイプの定義
ARG_TYPES = ["flag", "str", "int", "float", "list[int]", "list[float]"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pythonスクリプト ランチャー（PySide6）")
        self.resize(860, 600)

        # 状態
        self.current_folder: Path = Path.home()
        self.current_script: Path | None = None
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)  # stdout/stderrまとめて受信

        # UI構築
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- 上段：フォルダ選択 + スクリプト選択 ---
        folder_layout = QHBoxLayout()
        self.ed_folder = QLineEdit(str(self.current_folder))
        self.btn_browse = QPushButton("フォルダ選択...")
        self.btn_refresh = QPushButton("再読み込み")
        folder_layout.addWidget(QLabel("スクリプトフォルダ:"))
        folder_layout.addWidget(self.ed_folder, stretch=1)
        folder_layout.addWidget(self.btn_browse)
        folder_layout.addWidget(self.btn_refresh)

        script_layout = QHBoxLayout()
        self.cb_script = QComboBox()
        script_layout.addWidget(QLabel("スクリプト:"))
        script_layout.addWidget(self.cb_script, stretch=1)

        root.addLayout(folder_layout)
        root.addLayout(script_layout)

        # --- 中段：引数編集テーブル + 操作ボタン ---
        args_layout = QVBoxLayout()
        self.tbl_args = QTableWidget(0, 4)
        self.tbl_args.setHorizontalHeaderLabels(["有効", "名前/位置", "型", "値"])
        self.tbl_args.horizontalHeader().setStretchLastSection(True)
        self.tbl_args.verticalHeader().setVisible(False)

        btns_layout = QHBoxLayout()
        self.btn_add_arg = QPushButton("引数追加")
        self.btn_remove_arg = QPushButton("選択行を削除")
        self.btn_clear_args = QPushButton("すべてクリア")
        self.btn_save_preset = QPushButton("プリセット保存")
        btns_layout.addWidget(self.btn_add_arg)
        btns_layout.addWidget(self.btn_remove_arg)
        btns_layout.addWidget(self.btn_clear_args)
        btns_layout.addStretch(1)
        btns_layout.addWidget(self.btn_save_preset)

        #args_layout.addWidget(self.tbl_args)
        args_layout.addLayout(btns_layout)
        
        #root.addLayout(args_layout)
        
        
        # 推奨（引数テーブルを広く確保）：
        args_layout.addWidget(self.tbl_args)
        root.addLayout(args_layout, stretch=1)  # ← 引数エリアにストレッチを与える


        # --- 引数自動読み込み
        self.btn_import_parse = QPushButton("parse_argsから取り込み")
        btns_layout.addWidget(self.btn_import_parse)  # お好みの位置で
        self.btn_import_parse.clicked.connect(self.import_from_parse_args)



        # --- コマンドプレビュー + 実行/停止 ---
        cmd_layout = QGridLayout()
        # 置き換え後：
        self.lbl_cmd = QLabel()
        self.lbl_cmd.setWordWrap(True)  # ← 自動改行
        # 等幅フォントで見やすく（OS依存フォント名はなるべく一般的なものを指定）
        self.lbl_cmd.setStyleSheet("QLabel { font-family: Consolas, 'Courier New', monospace; }")

        self.btn_copy_cmd = QPushButton("📋 コピー")
        self.btn_copy_cmd.setToolTip("表示中のコマンドをクリップボードへコピー")
        self.btn_run = QPushButton("実行")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        # レイアウト調整（左：ラベル、右：コピー＋実行/停止）
        cmd_layout.addWidget(QLabel("コマンド:"), 0, 0)
        cmd_layout.addWidget(self.lbl_cmd, 0, 1, 1, 2)  # ラベルを広く
        cmd_layout.addWidget(self.btn_copy_cmd, 0, 3)
        cmd_layout.addWidget(self.btn_run, 1, 2)
        cmd_layout.addWidget(self.btn_stop, 1, 3)
        
        root.addLayout(cmd_layout)


        # --- 出力表示 ---
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
#        root.addWidget(QLabel("出力:"))
#        root.addWidget(self.out, stretch=1)

        # 推奨（引数を広く・出力は最小限）：
        root.addWidget(QLabel("出力:"))
        root.addWidget(self.out, stretch=0)  # 出力はストレッチしない

        
        # 出力ウィジェット作成後に追加
        self.out.setMaximumHeight(120)  # ← ログの縦幅を狭く（お好みで 120〜200 に調整）

        

        # メニュー（任意）
        act_exit = QAction("終了", self)
        act_exit.triggered.connect(self.close)
        file_menu = self.menuBar().addMenu("ファイル")
        file_menu.addAction(act_exit)

        # シグナル接続
        self.btn_browse.clicked.connect(self.choose_folder)
        self.btn_refresh.clicked.connect(self.refresh_scripts)
        self.cb_script.currentIndexChanged.connect(self.on_script_changed)

        self.btn_add_arg.clicked.connect(self.add_arg_row)
        self.btn_remove_arg.clicked.connect(self.remove_selected_rows)
        self.btn_clear_args.clicked.connect(self.clear_args)
        self.btn_save_preset.clicked.connect(self.save_preset)

        self.btn_run.clicked.connect(self.run_script)
        self.btn_stop.clicked.connect(self.stop_script)
        
        self.btn_copy_cmd.clicked.connect(lambda: QApplication.clipboard().setText(self.lbl_cmd.text()))

        # QProcess: 非同期出力
        self.proc.readyReadStandardOutput.connect(self.on_proc_output)
        self.proc.started.connect(lambda: self.set_running_ui(True))
        self.proc.finished.connect(self.on_proc_finished)
        self.proc.errorOccurred.connect(self.on_proc_error)

        # 初期読み込み
        self.refresh_scripts()
        self.update_command_preview()

    # ---------- フォルダ/スクリプト ----------
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "スクリプトフォルダを選択", str(self.current_folder))
        if d:
            self.current_folder = Path(d)
            self.ed_folder.setText(d)
            self.refresh_scripts()

    def refresh_scripts(self):
        folder = Path(self.ed_folder.text()).expanduser()
        if not folder.exists():
            QMessageBox.warning(self, "フォルダなし", f"存在しないフォルダです:\n{folder}")
            return
        self.current_folder = folder
        self.cb_script.blockSignals(True)
        self.cb_script.clear()
        py_files = sorted(folder.glob("*.py"))
        for p in py_files:
            self.cb_script.addItem(p.name, str(p))
        self.cb_script.blockSignals(False)

        if py_files:
            self.cb_script.setCurrentIndex(0)
            self.on_script_changed()
        else:
            self.current_script = None
            self.clear_args()
            self.update_command_preview()

    def on_script_changed(self):
        data = self.cb_script.currentData()
        self.current_script = Path(data) if data else None
        # スクリプト固有のプリセットをロード
        self.load_preset()
        self.update_command_preview()

    # ---------- 引数テーブル ----------
    def add_arg_row(self, arg: Dict[str, Any] | None = None):
        """
        arg: {"enabled": bool, "name": str, "type": "flag|str|int|float", "value": Any}
        nameが "--opt" ならオプション、"input.txt" などなら位置引数として扱う
        """
        row = self.tbl_args.rowCount()
        self.tbl_args.insertRow(row)

        # 有効（チェックボックス）
        chk = QCheckBox()
        chk.setChecked(True if not arg else bool(arg.get("enabled", True)))
        self.tbl_args.setCellWidget(row, 0, chk)

        # 名前（QTableWidgetItemで編集可）
        name_item = QTableWidgetItem("" if not arg else str(arg.get("name", "")))
        name_item.setFlags(name_item.flags() | Qt.ItemIsEditable)
        self.tbl_args.setItem(row, 1, name_item)

        # 型（コンボボックス）
        cb_type = QComboBox()
        cb_type.addItems(ARG_TYPES)
        cb_type.setCurrentText("str" if not arg else str(arg.get("type", "str")))
        self.tbl_args.setCellWidget(row, 2, cb_type)

        # 値（型に応じて）
        typ = cb_type.currentText()
        if typ == "int":
            w = QSpinBox()
            w.setRange(-1_000_000_000, 1_000_000_000)
            w.setValue(0 if not arg else int(arg.get("value", 0)))
        elif typ == "float":
            w = QDoubleSpinBox()
            w.setRange(-1e12, 1e12)
            w.setDecimals(6)
            w.setValue(0.0 if not arg else float(arg.get("value", 0.0)))
        elif typ == "flag":
            # flagは値不要だが、UI上はチェックボックスでON/OFFも可
            w = QCheckBox("ON/OFF")
            w.setChecked(True if not arg else bool(arg.get("value", True)))
            

        elif typ == "list[int]":
    # カンマ区切りで表現（例: "1,2,3"）
            default = "" if not arg else ",".join(map(str, arg.get("value") or []))
            w = QLineEdit(default)
        elif typ == "list[float]":
            default = "" if not arg else ",".join(map(str, arg.get("value") or []))
            w = QLineEdit(default)
        elif typ == "list[str]":
            default = "" if not arg else ",".join(map(str, arg.get("value") or []))
            w = QLineEdit(default)

            
        else:
            # str
            w = QLineEdit("" if not arg else str(arg.get("value", "")))
        self.tbl_args.setCellWidget(row, 3, w)

        # 型変更時に値ウィジェットを差し替え
        cb_type.currentTextChanged.connect(lambda t, r=row: self._rebuild_value_widget(r, t))

        self.update_command_preview()

    def _rebuild_value_widget(self, row: int, typ: str):
        # 現行値を文字列として保存（再生成時に復元するため）
        prev = self._value_widget_to_python(row)
        if typ == "int":
            w = QSpinBox()
            w.setRange(-1_000_000_000, 1_000_000_000)
            try:
                w.setValue(int(prev) if prev is not None else 0)
            except Exception:
                w.setValue(0)
        elif typ == "float":
            w = QDoubleSpinBox()
            w.setRange(-1e12, 1e12)
            w.setDecimals(6)
            try:
                w.setValue(float(prev) if prev is not None else 0.0)
            except Exception:
                w.setValue(0.0)
        elif typ == "flag":
            w = QCheckBox("ON/OFF")
            w.setChecked(bool(prev) if prev is not None else True)
        else:
            w = QLineEdit("" if prev is None else str(prev))
        self.tbl_args.setCellWidget(row, 3, w)
        self.update_command_preview()

    def remove_selected_rows(self):
        rows = sorted({idx.row() for idx in self.tbl_args.selectedIndexes()}, reverse=True)
        for r in rows:
            self.tbl_args.removeRow(r)
        self.update_command_preview()

    def clear_args(self):
        self.tbl_args.setRowCount(0)
        self.update_command_preview()

    def _value_widget_to_python(self, row: int):
        w = self.tbl_args.cellWidget(row, 3)
        if isinstance(w, QLineEdit):
            return w.text()
        if isinstance(w, QSpinBox):
            return w.value()
        if isinstance(w, QDoubleSpinBox):
            return w.value()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        return None

    def gather_args(self) -> List[str]:
        """
        テーブルからコマンドライン引数のリストを組み立てる
        - 名前が "--" で始まればオプション
          * flag型: "--opt"
          * str/int/float型: "--opt", "値"
        - それ以外は位置引数として "値" のみ
        """


        argv: List[str] = []
        for row in range(self.tbl_args.rowCount()):
            enabled = self.tbl_args.cellWidget(row, 0).isChecked()
            name_item = self.tbl_args.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            typ = self.tbl_args.cellWidget(row, 2).currentText()
            val = self._value_widget_to_python(row)

            if not enabled:
                continue

            def split_list_text(v: str) -> List[str]:
            # "1,2,3" → ["1","2","3"]（空白を除去）
                items = [x.strip() for x in v.split(",") if x.strip()]
                return items

            if name.startswith("-"):
            # オプション
                if typ == "flag":
                    if bool(val):
                        argv.append(name)
                elif typ == "list[int]" or typ == "list[float]" or typ == "list[str]":
                    argv.append(name)
                    argv.extend(split_list_text(val if isinstance(val, str) else ""))
                else:
                    argv.append(name)
                    argv.append(str(val))
            else:
            # 位置引数
                if typ == "flag":
                    if bool(val):
                        argv.append(name)
                elif typ == "list[int]" or typ == "list[float]" or typ == "list[str]":
                    argv.extend(split_list_text(val if isinstance(val, str) else ""))
                else:
                    argv.append(str(val))
        return argv



    # ---------- 実行 ----------
    def run_script(self):
        if self.proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "実行中", "すでにプロセスが実行中です。停止してから再実行してください。")
            return

        if not self.current_script or not self.current_script.exists():
            QMessageBox.warning(self, "スクリプト未選択", "実行する .py スクリプトを選択してください。")
            return

        # コマンド組み立て: 同じPythonインタプリタで実行（仮想環境対応）
        py = sys.executable
        script = str(self.current_script)
        argv = [py, script] + self.gather_args()

        # 出力クリア & 実行
        self.out.clear()
        self.out.appendPlainText(f"$ {' '.join(map(self._quote, argv))}\n")
        self.proc.setWorkingDirectory(str(self.current_folder))
        self.proc.start(py, [script] + self.gather_args())

        if not self.proc.waitForStarted(3000):  # 3秒で開始確認
            QMessageBox.critical(self, "起動失敗", "プロセスの起動に失敗しました。共有ライブラリや権限を確認してください。")

        self.update_command_preview()

    def stop_script(self):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.kill()

    def on_proc_output(self):
        data = bytes(self.proc.readAllStandardOutput()).decode(errors="ignore")
        self.out.appendPlainText(data)
        # 自動スクロール
        cursor = self.out.textCursor()
        cursor.movePosition(cursor.End)
        self.out.setTextCursor(cursor)

    def on_proc_finished(self, code, status):
        self.set_running_ui(False)
        self.out.appendPlainText(f"\n[終了] code={code}, status={status}")
        self.update_command_preview()

    def on_proc_error(self, err):
        self.set_running_ui(False)
        self.out.appendPlainText(f"\n[エラー] {err}")
        self.update_command_preview()

    def set_running_ui(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.cb_script.setEnabled(not running)
        self.btn_browse.setEnabled(not running)
        self.btn_refresh.setEnabled(not running)

    # --- 引数自動読み込み
    
    def import_from_parse_args(self):
        """
        現在選択中スクリプトのソースをAST解析し、parse_args()内のadd_argument()から
        引数定義を抽出してテーブルへ投入する。
        """
        if not self.current_script or not self.current_script.exists():
            QMessageBox.warning(self, "スクリプト未選択", "対象の .py スクリプトを選択してください。")
            return

        try:
            src = self.current_script.read_text(encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "読み込み失敗", f"スクリプトの読み込みに失敗しました:\n{e}")
            return

        try:
            rows = self._extract_args_from_parse_args(src)
        except Exception as e:
            QMessageBox.critical(self, "解析失敗", f"AST解析でエラーが発生しました:\n{e}")
            return

        if not rows:
            QMessageBox.information(self, "検出なし", "parse_args() から引数定義を検出できませんでした。")
            return

        self.clear_args()
        for r in rows:
            self.add_arg_row(r)
        self.update_command_preview()
        QMessageBox.information(self, "取り込み完了", f"{len(rows)} 個の引数を取り込みました。")


    # ---AST解析ロジック
    
    def _extract_args_from_parse_args(self, source: str):
        """
        `def parse_args():` の中で作られた ArgumentParser（例: 変数名 p）に対する
        p.add_argument(...) を抽出して、GUIテーブル用の辞書リストへ変換する。
        対応するキーワード: type, default, action, nargs, required, help
        """
        tree = ast.parse(source)
        rows = []

        # parse_args関数を探す
        parse_fn: ast.FunctionDef | None = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "parse_args":
                parse_fn = node
                break
        if parse_fn is None:
            return []  # 見つからなければ終了

    # 関数内で ArgumentParser を受け取る変数名（例: p）を特定
        parser_vars = set()
        for node in ast.walk(parse_fn):
            # p = argparse.ArgumentParser(...)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                cal = node.value
                if isinstance(cal.func, ast.Attribute) and isinstance(cal.func.value, ast.Name) and cal.func.value.id == "argparse" and cal.func.attr == "ArgumentParser":
                # 左辺のターゲット名（pなど）
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            parser_vars.add(tgt.id)

        if not parser_vars:
            return []

        def literal(x):
            """astリテラルをPython値へ（最小限）"""
            if isinstance(x, ast.Constant):
                return x.value
            if isinstance(x, ast.Tuple):
                return tuple(literal(e) for e in x.elts)
            if isinstance(x, ast.List):
                return [literal(e) for e in x.elts]
            if isinstance(x, ast.NameConstant):  # 古いPython用
                return x.value
            return None  # それ以外は扱わない

        def choose_opt_name(opts: list[str]) -> str:
            """長いオプション名（--long）を優先。なければ先頭。"""
            longs = [o for o in opts if o.startswith("--")]
            return longs[0] if longs else opts[0]

    # add_argument呼び出しを列挙
        for node in ast.walk(parse_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # p.add_argument(...)
                recv = node.func.value
                method = node.func.attr
                if method != "add_argument":
                    continue
            # 受け手がparser_varsのいずれか
                if not (isinstance(recv, ast.Name) and recv.id in parser_vars):
                    continue

            # 位置引数: オプション名／位置引数名（複数可）
                names = []
                for a in node.args:
                    val = literal(a)
                    if isinstance(a, ast.Constant) and isinstance(val, str):
                        names.append(val)

            # キーワード引数
                kwargs = {}
                for kw in node.keywords:
                    kwargs[kw.arg] = literal(kw.value)

            # 型判定
                action = kwargs.get("action")
                typ = kwargs.get("type")
                nargs = kwargs.get("nargs")
                default = kwargs.get("default")
                required = kwargs.get("required")

            # GUI行を生成
                if names and names[0].startswith("-"):
                # オプション
                    name = choose_opt_name(names)
                    if action in ("store_true", "store_false"):
                    # フラグ
                        rows.append({
                            "enabled": True,
                            "name": name,
                            "type": "flag",
                            "value": bool(default) if default is not None else (action == "store_true")
                        })
                    else:
                    # 値あり
                        t = "str"
                        if typ is int:
                            t = "int"
                        elif typ is float:
                            t = "float"

                    # nargs対応（リスト型）
                        if isinstance(nargs, int) and nargs >= 2:
                            t = "list[int]" if t == "int" else "list[float]" if t == "float" else "list[str]"
                        elif isinstance(nargs, str) and nargs in ("+", "*"):
                        # 可変長 → list型
                            t = "list[int]" if t == "int" else "list[float]" if t == "float" else "list[str]"

                        val = default
                        if val is None:
                        # 型に応じた初期値
                            if t == "int":
                                val = 0
                            elif t == "float":
                                val = 0.0
                            elif t.startswith("list"):
                                val = []  # 空リスト
                            else:
                                val = ""
                        rows.append({
                            "enabled": True if not required else True,
                            "name": name,
                            "type": t,
                            "value": val,
                        })
                else:
                # 位置引数
                    name = names[0] if names else ""
                    t = "str"
                    if typ is int:
                        t = "int"
                    elif typ is float:
                        t = "float"

                    if isinstance(nargs, int) and nargs >= 2:
                        t = "list[int]" if t == "int" else "list[float]" if t == "float" else "list[str]"
                    elif isinstance(nargs, str) and nargs in ("+", "*"):
                        t = "list[int]" if t == "int" else "list[float]" if t == "float" else "list[str]"

                    val = default
                    if val is None:
                        val = 0 if t == "int" else 0.0 if t == "float" else [] if t.startswith("list") else ""

                    rows.append({
                        "enabled": True if not required else True,
                        "name": name,
                        "type": t,
                        "value": val,
                    })

    # 重複除去（--long名優先）
        uniq, seen = [], set()
        for r in rows:
            key = (r["name"], r["type"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(r)
        return uniq



    # ---------- プリセット保存/読み込み ----------
    def preset_dir(self) -> Path:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
        d = base / APP_NAME / "presets"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def preset_path(self) -> Path | None:
        if not self.current_script:
            return None
        name = self.current_script.stem + ".json"
        return self.preset_dir() / name

    def save_preset(self):
        import json
        if not self.current_script:
            QMessageBox.information(self, "保存不可", "スクリプトが選択されていません。")
            return
        rows = []
        for r in range(self.tbl_args.rowCount()):
            enabled = self.tbl_args.cellWidget(r, 0).isChecked()
            name = self.tbl_args.item(r, 1).text() if self.tbl_args.item(r, 1) else ""
            typ = self.tbl_args.cellWidget(r, 2).currentText()
            val = self._value_widget_to_python(r)
            rows.append({"enabled": enabled, "name": name, "type": typ, "value": val})
        p = self.preset_path()
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "保存", f"プリセットを保存しました:\n{p}")
        except Exception as e:
            QMessageBox.critical(self, "保存失敗", f"プリセット保存に失敗しました:\n{e}")

    def load_preset(self):
        import json
        self.clear_args()
        p = self.preset_path()
        if p and p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    rows = json.load(f)
                for r in rows:
                    self.add_arg_row(r)
            except Exception:
                # 読み込み失敗時は空のまま
                pass

    # ---------- ユーティリティ ----------
    def update_command_preview(self):
        py = self._quote(sys.executable)
        script = self._quote(str(self.current_script)) if self.current_script else "(未選択)"
        args = " ".join(map(self._quote, self.gather_args()))
        self.lbl_cmd.setText(f"コマンド: {py} {script} {args}")

    @staticmethod
    def _quote(s: Any) -> str:
        t = str(s)
        return f'"{t}"' if " " in t else t


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
