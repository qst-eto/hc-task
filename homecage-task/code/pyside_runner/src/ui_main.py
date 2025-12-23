
# -*- coding: utf-8 -*-
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt, QProcess, QStandardPaths
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFileDialog, QMessageBox, QSizePolicy,
    QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget,
    QTableWidgetItem, QCheckBox, QPlainTextEdit, QSpinBox, QDoubleSpinBox
)

# --- 外部関数の読み込み（モジュール名はあなたの環境に合わせて変更してください） ---
# 例: ops.py に関数が定義されている想定
try:
    from ops import rec_standby, rec_start, video_start, rec_end, touch_disable, shut_down
except Exception:
    # 開発・テスト用のダミー（本番は必ず正しいモジュールに差し替え）
    def rec_standby(): print("[stub] rec_standby")
    def rec_start(): print("[stub] rec_start")
    def video_start(): print("[stub] video_start")
    def touch_disable(): print("[stub] touch_disable")
    def shut_down(): print("[stub] shut_down")

from argparse_ast import extract_args_from_source, ARG_TYPES

APP_NAME = 'PyScriptRunner'

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Pythonスクリプト ランチャー（PySide6）')
        self.resize(1000, 680)

        # 状態
        self.current_folder: Path = Path.home()
        self.current_script: Path | None = None
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)

        # UI
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # フォルダ＆スクリプト選択
        folder_layout = QHBoxLayout()
        self.ed_folder = QLineEdit(str(self.current_folder))
        self.btn_browse = QPushButton('フォルダ選択...')
        self.btn_refresh = QPushButton('再読み込み')
        folder_layout.addWidget(QLabel('スクリプトフォルダ:'))
        folder_layout.addWidget(self.ed_folder, stretch=1)
        folder_layout.addWidget(self.btn_browse)
        folder_layout.addWidget(self.btn_refresh)

        script_layout = QHBoxLayout()
        self.cb_script = QComboBox()
        script_layout.addWidget(QLabel('スクリプト:'))
        script_layout.addWidget(self.cb_script, stretch=1)

        root.addLayout(folder_layout)
        root.addLayout(script_layout)


        # --- 追加: モード設定（ビデオモード／転送モード／シャットダウンモード） ---
        modes_layout = QHBoxLayout()
        self.cb_video_mode = QComboBox()
        self.cb_video_mode.addItems(['録画', '映像', 'なし'])
        self.cb_video_mode.setCurrentText('なし')

        self.chk_transfer = QCheckBox('転送モード（終了後 touch_disable）')
        self.chk_shutdown = QCheckBox('シャットダウンモード（転送後 shut_down）')

        modes_layout.addWidget(QLabel('ビデオモード:'))
        modes_layout.addWidget(self.cb_video_mode)
        modes_layout.addSpacing(20)
        modes_layout.addWidget(self.chk_transfer)
        modes_layout.addSpacing(10)
        modes_layout.addWidget(self.chk_shutdown)

        root.addLayout(modes_layout)


        # 引数テーブル＋ボタン帯
        args_layout = QVBoxLayout()
        self.tbl_args = QTableWidget(0, 4)
        self.tbl_args.setHorizontalHeaderLabels(['有効','名前/位置','型','値'])
        self.tbl_args.horizontalHeader().setStretchLastSection(True)
        self.tbl_args.verticalHeader().setVisible(False)
        self.tbl_args.verticalHeader().setDefaultSectionSize(28)

        btns_layout = QHBoxLayout()
        self.btn_add_arg = QPushButton('引数追加')
        self.btn_remove_arg = QPushButton('選択行を削除')
        self.btn_clear_args = QPushButton('すべてクリア')
        self.btn_import_parse = QPushButton('parse_argsから取り込み')
        self.btn_save_preset = QPushButton('プリセット保存')
        btns_layout.addWidget(self.btn_add_arg)
        btns_layout.addWidget(self.btn_remove_arg)
        btns_layout.addWidget(self.btn_clear_args)
        btns_layout.addWidget(self.btn_import_parse)
        btns_layout.addStretch(1)
        btns_layout.addWidget(self.btn_save_preset)

        args_layout.addWidget(self.tbl_args)
        args_layout.addLayout(btns_layout)
        root.addLayout(args_layout, stretch=1)  # 引数エリアを広く

        # コマンド表示＋実行停止（折返し・コピー対応）
        cmd_layout = QGridLayout()
        cmd_layout.addWidget(QLabel('コマンド:'), 0, 0)
        self.lbl_cmd = QLabel()
        self.lbl_cmd.setWordWrap(True)
        self.lbl_cmd.setStyleSheet("QLabel { font-family: Consolas, 'Courier New', monospace; }")
        self.lbl_cmd.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_cmd.setMaximumHeight(60)
        self.btn_copy_cmd = QPushButton('コピー')
        self.btn_run = QPushButton('実行')
        self.btn_stop = QPushButton('停止')
        self.btn_stop.setEnabled(False)
        cmd_layout.addWidget(self.lbl_cmd, 0, 1, 1, 2)
        cmd_layout.addWidget(self.btn_copy_cmd, 0, 3)
        cmd_layout.addWidget(self.btn_run, 1, 2)
        cmd_layout.addWidget(self.btn_stop, 1, 3)
        root.addLayout(cmd_layout)

        # 出力（縦幅を抑制）
        root.addWidget(QLabel('出力:'))
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumHeight(160)  # 出力の縦幅を抑制
        self.out.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self.out, stretch=0)

        # メニュー
        act_exit = QAction('終了', self)
        act_exit.triggered.connect(self.close)
        file_menu = self.menuBar().addMenu('ファイル')
        file_menu.addAction(act_exit)

        # シグナル
        self.btn_browse.clicked.connect(self.choose_folder)
        self.btn_refresh.clicked.connect(self.refresh_scripts)
        self.cb_script.currentIndexChanged.connect(self.on_script_changed)

        self.btn_add_arg.clicked.connect(self.add_arg_row)
        self.btn_remove_arg.clicked.connect(self.remove_selected_rows)
        self.btn_clear_args.clicked.connect(self.clear_args)
        self.btn_import_parse.clicked.connect(self.import_from_parse_args)
        self.btn_save_preset.clicked.connect(self.save_preset)

        self.btn_run.clicked.connect(self.run_script)
        self.btn_stop.clicked.connect(self.stop_script)
        self.btn_copy_cmd.clicked.connect(lambda: self._copy_cmd())

        self.proc.readyReadStandardOutput.connect(self.on_proc_output)
        self.proc.started.connect(lambda: self.set_running_ui(True))
        self.proc.finished.connect(self.on_proc_finished)
        self.proc.errorOccurred.connect(self.on_proc_error)

        # 初期化
        self.refresh_scripts()
        self.update_command_preview()

    # ---------- フォルダ/スクリプト ----------
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, 'スクリプトフォルダを選択', str(self.current_folder))
        if d:
            self.current_folder = Path(d)
            self.ed_folder.setText(d)
            self.refresh_scripts()

    def refresh_scripts(self):
        folder = Path(self.ed_folder.text()).expanduser()
        if not folder.exists():
            QMessageBox.warning(self, 'フォルダなし', f'存在しないフォルダです:\n{folder}')
            return
        self.current_folder = folder
        self.cb_script.blockSignals(True)
        self.cb_script.clear()
        py_files = sorted(folder.glob('*.py'))
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
        self.load_preset()
        self.update_command_preview()

    # ---------- 引数テーブル ----------
    def add_arg_row(self, arg: Dict[str, Any] | None = None):
        row = self.tbl_args.rowCount()
        self.tbl_args.insertRow(row)

        # 有効
        chk = QCheckBox()
        chk.setChecked(True if not arg else bool(arg.get('enabled', True)))
        self.tbl_args.setCellWidget(row, 0, chk)

        # 名前
        name_item = QTableWidgetItem('' if not arg else str(arg.get('name', '')))
        name_item.setFlags(name_item.flags() | Qt.ItemIsEditable)
        self.tbl_args.setItem(row, 1, name_item)

        # 型
        cb_type = QComboBox()
        cb_type.addItems(ARG_TYPES)
        cb_type.setCurrentText('str' if not arg else str(arg.get('type', 'str')))
        self.tbl_args.setCellWidget(row, 2, cb_type)

        # 値
        typ = cb_type.currentText()
        w = self._make_value_widget(typ, arg)
        self.tbl_args.setCellWidget(row, 3, w)

        cb_type.currentTextChanged.connect(lambda t, r=row: self._rebuild_value_widget(r, t))
        self.update_command_preview()

    def _make_value_widget(self, typ: str, arg: Dict[str, Any] | None):
        if typ == 'int':
            w = QSpinBox(); w.setRange(-1_000_000_000, 1_000_000_000)
            w.setValue(0 if not arg else int(arg.get('value', 0)))
            return w
        if typ == 'float':
            w = QDoubleSpinBox(); w.setRange(-1e12, 1e12); w.setDecimals(6)
            w.setValue(0.0 if not arg else float(arg.get('value', 0.0)))
            return w
        if typ == 'flag':
            w = QCheckBox('ON/OFF')
            w.setChecked(True if not arg else bool(arg.get('value', True)))
            return w
        if typ in ('list[int]', 'list[float]', 'list[str]'):
            default = '' if not arg else ','.join(map(str, arg.get('value') or []))
            w = QLineEdit(default)
            return w
        return QLineEdit('' if not arg else str(arg.get('value', '')))

    def _rebuild_value_widget(self, row: int, typ: str):
        prev = self._value_widget_to_python(row)
        arg = {'value': prev}
        w = self._make_value_widget(typ, arg)
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
        argv: List[str] = []
        for row in range(self.tbl_args.rowCount()):
            enabled = self.tbl_args.cellWidget(row, 0).isChecked()
            name_item = self.tbl_args.item(row, 1)
            name = name_item.text().strip() if name_item else ''
            typ = self.tbl_args.cellWidget(row, 2).currentText()
            val = self._value_widget_to_python(row)
            if not enabled:
                continue

            def split_list_text(v: str) -> List[str]:
                items = [x.strip() for x in v.split(',') if x.strip()]
                return items

            if name.startswith('-'):
                if typ == 'flag':
                    if bool(val):
                        argv.append(name)
                elif typ in ('list[int]', 'list[float]', 'list[str]'):
                    argv.append(name)
                    argv.extend(split_list_text(val if isinstance(val, str) else ''))
                else:
                    argv.append(name)
                    argv.append(str(val))
            else:
                if typ == 'flag':
                    if bool(val):
                        argv.append(name)
                elif typ in ('list[int]', 'list[float]', 'list[str]'):
                    argv.extend(split_list_text(val if isinstance(val, str) else ''))
                else:
                    argv.append(str(val))
        return argv

    # ---------- 実行 ----------

    def run_script(self):
        if self.proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, '実行中', 'すでにプロセスが実行中です。停止してから再実行してください。')
            return
        if not self.current_script or not self.current_script.exists():
            QMessageBox.warning(self, 'スクリプト未選択', '実行する .py スクリプトを選択してください。')
            return

    # 前処理（ビデオモード）
        mode = self.cb_video_mode.currentText()
        try:
            if mode == '録画':
                self.out.appendPlainText('[前処理] rec_standby → rec_start')
                rec_standby()
                rec_start()
            elif mode == '映像':
                self.out.appendPlainText('[前処理] rec_standby → video_start')
                rec_standby()
                video_start()
            else:
                self.out.appendPlainText('[前処理] ビデオモードなし（スルー）')
        except Exception as e:
            QMessageBox.critical(self, '前処理失敗', f'ビデオモードの前処理で失敗しました:\n{e}')
            return

        py = sys.executable
        script = str(self.current_script)
        args = self.gather_args()

        self.out.clear()
        preview = f'$ {self._quote(py)} {self._quote(script)} ' + ' '.join(map(self._quote, args))
        self.out.appendPlainText(preview + '\n')

        self.proc.setWorkingDirectory(str(self.current_folder))
        self.proc.start(py, [script] + args)
        if not self.proc.waitForStarted(3000):
            QMessageBox.critical(self, '起動失敗', 'プロセスの起動に失敗しました。共有ライブラリや権限を確認してください。')
        self.update_command_preview()


    def stop_script(self):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.kill()

    def on_proc_output(self):
        data = bytes(self.proc.readAllStandardOutput()).decode(errors='ignore')
        self.out.appendPlainText(data)
        cursor = self.out.textCursor(); cursor.movePosition(cursor.End)
        self.out.setTextCursor(cursor)


    def on_proc_finished(self, code, status):
        global sd_mode
        self.set_running_ui(False)
        self.out.appendPlainText(f'\n[終了] code={code}, status={status}')

    # 後処理：ビデオモードが録画/映像なら rec_end を最初に実行
        mode = self.cb_video_mode.currentText()
        try:
            if mode in ('録画', '映像'):
                self.out.appendPlainText('[後処理] rec_end')
                rec_end()
            else:
                self.out.appendPlainText('[後処理] ビデオモードなし（rec_endスルー）')
        except Exception as e:
            self.out.appendPlainText(f'[後処理エラー] rec_end: {e}')

    # 続けて転送 → シャットダウン
        try:
            if self.chk_transfer.isChecked():
                self.out.appendPlainText('[後処理] touch_disable')
                touch_disable()
            else:
                self.out.appendPlainText('[後処理] 転送モードなし（スルー）')

            if self.chk_shutdown.isChecked():
                self.out.appendPlainText('[後処理] shut_down')
                shut_down()
            elif sd_mode=True:
                self.out.appendPlainText('[後処理] shut_down')
                shut_down()                
            else:
                self.out.appendPlainText('[後処理] シャットダウンモードなし（スルー）')
        except Exception as e:
            self.out.appendPlainText(f'[後処理エラー] {e}')

        self.update_command_preview()


    def on_proc_error(self, err):
        self.set_running_ui(False)
        self.out.appendPlainText(f'\n[エラー] {err}')
        self.update_command_preview()

    def set_running_ui(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.cb_script.setEnabled(not running)
        self.btn_browse.setEnabled(not running)
        self.btn_refresh.setEnabled(not running)

    # ---------- プリセット ----------
    def preset_dir(self) -> Path:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
        d = base / APP_NAME / 'presets'
        d.mkdir(parents=True, exist_ok=True)
        return d

    def preset_path(self) -> Path | None:
        if not self.current_script:
            return None
        name = self.current_script.stem + '.json'
        return self.preset_dir() / name

    def save_preset(self):
        import json
        if not self.current_script:
            QMessageBox.information(self, '保存不可', 'スクリプトが選択されていません。')
            return
        rows = []
        for r in range(self.tbl_args.rowCount()):
            enabled = self.tbl_args.cellWidget(r, 0).isChecked()
            name = self.tbl_args.item(r, 1).text() if self.tbl_args.item(r, 1) else ''
            typ = self.tbl_args.cellWidget(r, 2).currentText()
            val = self._value_widget_to_python(r)
            if isinstance(val, str) and typ in ('list[int]', 'list[float]', 'list[str]'):
                items = [x.strip() for x in val.split(',') if x.strip()]
                val = items
            rows.append({'enabled': enabled, 'name': name, 'type': typ, 'value': val})
        p = self.preset_path()
        try:
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, '保存', f'プリセットを保存しました:\n{p}')
        except Exception as e:
            QMessageBox.critical(self, '保存失敗', f'プリセット保存に失敗しました:\n{e}')

    def load_preset(self):
        import json
        self.clear_args()
        p = self.preset_path()
        if p and p.exists():
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    rows = json.load(f)
                for r in rows:
                    self.add_arg_row(r)
            except Exception:
                pass

    # ---------- 取り込み ----------
    def import_from_parse_args(self):
        if not self.current_script or not self.current_script.exists():
            QMessageBox.warning(self, 'スクリプト未選択', '対象の .py スクリプトを選択してください。')
            return
        try:
            src = self.current_script.read_text(encoding='utf-8')
        except Exception as e:
            QMessageBox.critical(self, '読み込み失敗', f'スクリプトの読み込みに失敗しました:\n{e}')
            return
        try:
            rows = extract_args_from_source(src)
        except Exception as e:
            QMessageBox.critical(self, '解析失敗', f'AST解析でエラーが発生しました:\n{e}')
            return
        if not rows:
            QMessageBox.information(self, '検出なし', 'parse_args() から引数定義を検出できませんでした。')
            return
        self.clear_args()
        for r in rows:
            self.add_arg_row(r)
        self.update_command_preview()
        QMessageBox.information(self, '取り込み完了', f'{len(rows)} 個の引数を取り込みました。')

    # ---------- ユーティリティ ----------
    def update_command_preview(self):
        py = self._quote(sys.executable)
        script = self._quote(str(self.current_script)) if self.current_script else '(未選択)'
        args = ' '.join(map(self._quote, self.gather_args()))
        self.lbl_cmd.setText(f'{py} {script} {args}')

    def _copy_cmd(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.lbl_cmd.text())

    @staticmethod
    def _quote(s: Any) -> str:
        t = str(s)
        return f'"{t}"' if ' ' in t else t
