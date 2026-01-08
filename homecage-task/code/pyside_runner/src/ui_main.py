
# -*- coding: utf-8 -*-
from __future__ import annotations
import sys
import shlex
import re
import datetime
from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import Qt, QProcess, QStandardPaths, QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFileDialog, QMessageBox, QSizePolicy,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget,
    QTableWidgetItem, QCheckBox, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
    QDialog
)

# --- 外部関数の読み込み ---
try:
    from ops import (
        rec_standby, rec_start, video_start, rec_end,
        touch_disable, shut_down, set_transfer_config
    )
except Exception:
    # スタブ（開発用）
    def rec_standby(): print("[stub] rec_standby")
    def rec_start(): print("[stub] rec_start")
    def video_start(): print("[stub] video_start")
    def rec_end(): print("[stub] rec_end")
    def touch_disable(): print("[stub] touch_disable")
    def shut_down(): print("[stub] shut_down")
    def set_transfer_config(**kwargs): print("[stub] set_transfer_config", kwargs)

from argparse_ast import extract_args_from_source, ARG_TYPES

APP_NAME = 'PyScriptRunner'
ORG_NAME = 'EtoHayato'  # QSettings 識別

# --- ホイール無効コンボボックス ---
class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()

# --- 転送設定ダイアログ ---
class TransferSettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, init: Dict[str, Any] | None = None):
        super().__init__(parent)
        self.setWindowTitle("転送設定")
        self.setMinimumWidth(520)

        self.ed_host = QLineEdit()
        self.sp_port = QSpinBox(); self.sp_port.setRange(1, 65535)
        self.ed_user = QLineEdit()
        self.ed_pass = QLineEdit(); self.ed_pass.setEchoMode(QLineEdit.Password)
        self.ed_ras = QLineEdit()
        self.ed_win = QLineEdit()

        btn_ras = QPushButton("Piログフォルダ…")
        btn_win = QPushButton("保存先フォルダ…")
        btn_ras.clicked.connect(self.choose_ras_dir)
        btn_win.clicked.connect(self.choose_win_dir)

        form = QFormLayout()
        form.addRow("ホスト名", self.ed_host)
        form.addRow("ポート", self.sp_port)
        form.addRow("ユーザー名", self.ed_user)
        form.addRow("パスワード", self.ed_pass)

        ras_layout = QHBoxLayout()
        ras_layout.addWidget(self.ed_ras, stretch=1)
        ras_layout.addWidget(btn_ras)
        form.addRow("Logのパス（Pi側）", ras_layout)

        win_layout = QHBoxLayout()
        win_layout.addWidget(self.ed_win, stretch=1)
        win_layout.addWidget(btn_win)
        form.addRow("保存先のパス（Windows側）", win_layout)

        btn_ok = QPushButton("保存")
        btn_cancel = QPushButton("キャンセル")
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(btn_cancel)
        btns.addWidget(btn_ok)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(btns)

        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        # 初期値の反映
        if init:
            self.ed_host.setText(init.get("host", "hc-task02.local"))
            self.sp_port.setValue(int(init.get("port", 22)))
            self.ed_user.setText(init.get("username", "user"))
            self.ed_pass.setText(init.get("password", "user"))
            self.ed_ras.setText(init.get("ras_path", "./logs"))
            self.ed_win.setText(init.get("win_path", "C:/Users/user/Desktop/logs/280"))

    def choose_ras_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Piログフォルダを選択", self.ed_ras.text() or str(Path.home()))
        if d:
            self.ed_ras.setText(d)

    def choose_win_dir(self):
        d = QFileDialog.getExistingDirectory(self, "保存先フォルダを選択", self.ed_win.text() or str(Path.home()))
        if d:
            self.ed_win.setText(d)

    def values(self) -> Dict[str, Any]:
        return {
            "host": self.ed_host.text().strip(),
            "port": int(self.sp_port.value()),
            "username": self.ed_user.text().strip(),
            "password": self.ed_pass.text(),
            "ras_path": self.ed_ras.text().strip(),
            "win_path": self.ed_win.text().strip(),
        }

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Pythonスクリプト ランチャー（PySide6）')
        self.resize(1080, 700)

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
        self.cb_script = NoWheelComboBox()
        script_layout.addWidget(QLabel('スクリプト:'))
        script_layout.addWidget(self.cb_script, stretch=1)

        root.addLayout(folder_layout)
        root.addLayout(script_layout)

        # モード設定
        modes_layout = QHBoxLayout()
        self.cb_video_mode = NoWheelComboBox()
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

        # 貼り付け入力
        paste_layout = QHBoxLayout()
        self.paste_input = QPlainTextEdit()
        self.paste_input.setPlaceholderText(
            "ここにコマンドラインを貼り付けてください（例）\n"
            "python /path/to/script.py --window-w 1280 --rect-rgb 0 160 255 input.txt"
        )
        self.paste_input.setMaximumHeight(100)
        self.btn_import_text = QPushButton('貼り付け→引数読み込み')
        self.btn_import_clip = QPushButton('クリップボードから読み込み')
        paste_layout.addWidget(QLabel("貼り付け入力:"))
        paste_layout.addWidget(self.paste_input, stretch=1)
        paste_layout.addWidget(self.btn_import_text)
        paste_layout.addWidget(self.btn_import_clip)
        root.addLayout(paste_layout)

        # 引数テーブル＋ボタン帯
        args_layout = QVBoxLayout()
        self.tbl_args = QTableWidget(0, 4)
        self.tbl_args.setHorizontalHeaderLabels(['有効', '名前/位置', '型', '値'])
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
        root.addLayout(args_layout, stretch=1)

        # コマンド表示＋実行停止
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

        # 出力
        root.addWidget(QLabel('出力:'))
        self.out = QPlainTextEdit(); self.out.setReadOnly(True)
        self.out.setMaximumHeight(160)
        self.out.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self.out, stretch=0)

        # メニュー
        act_exit = QAction('終了', self); act_exit.triggered.connect(self.close)
        file_menu = self.menuBar().addMenu('ファイル'); file_menu.addAction(act_exit)

        # 新規：設定メニュー
        settings_menu = self.menuBar().addMenu('設定')
        act_transfer = QAction('転送設定...', self)
        act_transfer.triggered.connect(self.open_transfer_settings)
        settings_menu.addAction(act_transfer)

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
        self.btn_import_text.clicked.connect(self.import_args_from_pasted_text)
        self.btn_import_clip.clicked.connect(self.import_args_from_clipboard)

        self.proc.readyReadStandardOutput.connect(self.on_proc_output)
        self.proc.started.connect(lambda: self.set_running_ui(True))
        self.proc.finished.connect(self.on_proc_finished)
        self.proc.errorOccurred.connect(self.on_proc_error)

        # 初期化：前回状態の復元（フォルダ/スクリプト/モード＋転送設定）
        self.load_app_state()
        self.load_transfer_settings()   # ← 新規：QSettingsから転送設定を読み込み、opsへ反映
        self.update_command_preview()

    # ---------- 設定ダイアログ関連 ----------
    def open_transfer_settings(self):
        vals = self.get_transfer_settings()
        dlg = TransferSettingsDialog(self, init=vals)
        if dlg.exec() == QDialog.Accepted:
            new_vals = dlg.values()
            # QSettings へ保存
            s = QSettings(ORG_NAME, APP_NAME)
            s.setValue("transfer/host", new_vals["host"])
            s.setValue("transfer/port", new_vals["port"])
            s.setValue("transfer/username", new_vals["username"])
            s.setValue("transfer/password", new_vals["password"])
            s.setValue("transfer/ras_path", new_vals["ras_path"])
            s.setValue("transfer/win_path", new_vals["win_path"])
            s.sync()
            # ops へ反映
            set_transfer_config(**new_vals)
            QMessageBox.information(self, "保存", "転送設定を保存しました。\n次回以降もこの設定が利用されます。")

    def get_transfer_settings(self) -> Dict[str, Any]:
        s = QSettings(ORG_NAME, APP_NAME)
        return {
            "host": s.value("transfer/host", "hc-task02.local", type=str),
            "port": s.value("transfer/port", 22, type=int),
            "username": s.value("transfer/username", "user", type=str),
            "password": s.value("transfer/password", "user", type=str),
            "ras_path": s.value("transfer/ras_path", "./logs", type=str),
            "win_path": s.value("transfer/win_path", "C:/Users/user/Desktop/logs/280", type=str),
        }

    def load_transfer_settings(self):
        """起動時に転送設定をロードし、opsへ反映。"""
        vals = self.get_transfer_settings()
        set_transfer_config(**vals)

    # ---------- QSettings：前回状態の保存/復元 ----------
    def load_app_state(self):
        s = QSettings(ORG_NAME, APP_NAME)
        last_folder = s.value("last_folder", "", type=str)
        last_script = s.value("last_script", "", type=str)
        video_mode = s.value("video_mode", "なし", type=str)
        transfer_on = s.value("transfer_on", False, type=bool)
        shutdown_on = s.value("shutdown_on", False, type=bool)

        if last_folder:
            self.ed_folder.setText(last_folder)
        self.refresh_scripts()

        if last_script:
            idx = self.cb_script.findText(Path(last_script).name)
            if idx >= 0:
                self.cb_script.setCurrentIndex(idx)

        self.cb_video_mode.setCurrentText(video_mode if video_mode in ("録画", "映像", "なし") else "なし")
        self.chk_transfer.setChecked(bool(transfer_on))
        self.chk_shutdown.setChecked(bool(shutdown_on))

    def save_app_state(self):
        s = QSettings(ORG_NAME, APP_NAME)
        s.setValue("last_folder", self.ed_folder.text())
        s.setValue("last_script", str(self.current_script) if self.current_script else "")
        s.setValue("video_mode", self.cb_video_mode.currentText())
        s.setValue("transfer_on", self.chk_transfer.isChecked())
        s.setValue("shutdown_on", self.chk_shutdown.isChecked())
        s.sync()

    def closeEvent(self, event):
        try:
            self.save_app_state()
            self.save_preset(auto=True)
        finally:
            super().closeEvent(event)

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
            if self.cb_script.currentIndex() < 0:
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

        chk = QCheckBox()
        chk.setChecked(False if not arg else bool(arg.get('enabled', False)))
        self.tbl_args.setCellWidget(row, 0, chk)

        name_item = QTableWidgetItem('' if not arg else str(arg.get('name', '')))
        name_item.setFlags(name_item.flags() | Qt.ItemIsEditable)
        self.tbl_args.setItem(row, 1, name_item)

        cb_type = NoWheelComboBox()
        type_choices = list(dict.fromkeys(ARG_TYPES + ['list[str]']))
        cb_type.addItems(type_choices)
        cb_type.setCurrentText('str' if not arg else str(arg.get('type', 'str')))
        self.tbl_args.setCellWidget(row, 2, cb_type)

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
        if isinstance(w, QLineEdit): return w.text()
        if isinstance(w, QSpinBox): return w.value()
        if isinstance(w, QDoubleSpinBox): return w.value()
        if isinstance(w, QCheckBox): return w.isChecked()
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

    # 行検索＆更新（貼り付け→マージ用）
    def _row_index_by_name(self, name: str) -> int:
        for r in range(self.tbl_args.rowCount()):
            item = self.tbl_args.item(r, 1)
            if item and item.text().strip() == name.strip():
                return r
        return -1

    def _set_row(self, row: int, typ: str, value: Any, enabled: bool = True):
        cb_type = self.tbl_args.cellWidget(row, 2)
        if isinstance(cb_type, QComboBox):
            cb_type.setCurrentText(typ)
            self._rebuild_value_widget(row, typ)

        w = self.tbl_args.cellWidget(row, 3)
        if typ.startswith('list'):
            text = ",".join(map(str, value if isinstance(value, list) else [value]))
            if isinstance(w, QLineEdit):
                w.setText(text)
        elif typ == 'int' and isinstance(w, QSpinBox):
            try: w.setValue(int(value))
            except Exception: w.setValue(0)
        elif typ == 'float' and isinstance(w, QDoubleSpinBox):
            try: w.setValue(float(value))
            except Exception: w.setValue(0.0)
        elif typ == 'flag' and isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        else:
            if isinstance(w, QLineEdit):
                w.setText(str(value))

        chk = self.tbl_args.cellWidget(row, 0)
        if isinstance(chk, QCheckBox):
            chk.setChecked(bool(enabled))

    # ---------- コマンドファイル出力（追記） ----------
    def command_file_path(self) -> Path:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
        base = base / APP_NAME
        base.mkdir(parents=True, exist_ok=True)
        return base / "last_command.txt"

    def write_last_command(self, text: str):
        try:
            p = self.command_file_path()
            with open(p, "a", encoding="utf-8") as f:
                f.write(text + "\n")
            self.out.appendPlainText(f"[コマンド保存] {p}")
        except Exception as e:
            self.out.appendPlainText(f"[コマンド保存エラー] {e}")

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
                rec_standby(); rec_start()
            elif mode == '映像':
                self.out.appendPlainText('[前処理] rec_standby → video_start')
                rec_standby(); video_start()
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

        # 追記：開始時刻／コマンド本文
        self.write_last_command("script start " + datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S'))
        self.write_last_command(preview)

        # 実行
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
        self.set_running_ui(False)
        self.out.appendPlainText(f'\n[終了] code={code}, status={status}')

        # 追記：終了時刻
        self.write_last_command("script stop " + datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S') + "\n")

        # 後処理：rec_end → transfer → shutdown
        mode = self.cb_video_mode.currentText()
        try:
            if mode in ('録画', '映像'):
                self.out.appendPlainText('[後処理] rec_end')
                rec_end()
            else:
                self.out.appendPlainText('[後処理] ビデオモードなし（rec_endスルー）')
        except Exception as e:
            self.out.appendPlainText(f'[後処理エラー] rec_end: {e}')

        try:
            if self.chk_transfer.isChecked():
                self.out.appendPlainText('[後処理] touch_disable')
                touch_disable()
            else:
                self.out.appendPlainText('[後処理] 転送モードなし（スルー）')

            if self.chk_shutdown.isChecked():
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

    # ---------- プリセット（JSON）：引数＋モード ----------
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

    def save_preset(self, auto: bool = False):
        import json
        if not self.current_script:
            if not auto:
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

        data = {
            'args': rows,
            'video_mode': self.cb_video_mode.currentText(),
            'transfer_on': self.chk_transfer.isChecked(),
            'shutdown_on': self.chk_shutdown.isChecked(),
        }

        p = self.preset_path()
        try:
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if not auto:
                QMessageBox.information(self, '保存', f'プリセットを保存しました:\n{p}')
        except Exception as e:
            if not auto:
                QMessageBox.critical(self, '保存失敗', f'プリセット保存に失敗しました:\n{e}')

    def load_preset(self):
        import json
        self.clear_args()
        p = self.preset_path()
        if not p or not p.exists():
            return
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for r in data.get('args', []):
                self.add_arg_row(r)
            vm = data.get('video_mode')
            if vm in ('録画', '映像', 'なし'):
                self.cb_video_mode.setCurrentText(vm)
            self.chk_transfer.setChecked(bool(data.get('transfer_on', self.chk_transfer.isChecked())))
            self.chk_shutdown.setChecked(bool(data.get('shutdown_on', self.chk_shutdown.isChecked())))
        except Exception:
            pass

    # ---------- parse_args 取り込み（全無効） ----------
    def import_from_parse_args(self):
        if not self.current_script or not self.current_script.exists():
            QMessageBox.warning(self, 'スクリプト未選択', '対象の .py スクリプトを選択してください。')
            return
        try:
            src = self.current_script.read_text(encoding='utf-8')
            rows = extract_args_from_source(src)
        except Exception as e:
            QMessageBox.critical(self, '解析失敗', f'AST解析でエラーが発生しました:\n{e}')
            return
        if not rows:
            QMessageBox.information(self, '検出なし', 'parse_args() から引数定義を検出できませんでした。')
            return

        self.clear_args()
        for r in rows:
            r['enabled'] = False
            self.add_arg_row(r)

        self.update_command_preview()
        QMessageBox.information(self, '取り込み完了', f'{len(rows)} 個の引数を（すべて無効として）取り込みました。')

    # ---------- 貼り付けテキストから引数復元（該当のみ有効化） ----------
    def import_args_from_clipboard(self):
        from PySide6.QtWidgets import QApplication
        text = QApplication.clipboard().text()
        self.paste_input.setPlainText(text)
        self.import_args_from_pasted_text()

    def import_args_from_pasted_text(self):
        if not self.current_script or not self.current_script.exists():
            QMessageBox.warning(self, 'スクリプト未選択', '対象の .py スクリプトを選択してください。')
            return
        raw = self.paste_input.toPlainText().strip()
        if not raw:
            QMessageBox.information(self, '入力なし', '貼り付けテキストが空です。')
            return

        try:
            src = self.current_script.read_text(encoding='utf-8')
            schema = extract_args_from_source(src)
        except Exception as e:
            QMessageBox.critical(self, '解析失敗', f'AST解析でエラーが発生しました:\n{e}')
            return

        opt_info: Dict[str, Dict[str, Any]] = {}
        positional_names: List[str] = []
        for r in schema:
            name = r.get('name', '')
            if name.startswith('-'): opt_info[name] = r
            else: positional_names.append(name)

        try:
            toks: List[str] = shlex.split(raw)
        except Exception as e:
            QMessageBox.critical(self, '解析失敗', f'コマンドラインの分割に失敗しました:\n{e}')
            return

        cleaned: List[str] = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if i == 0 and re.search(r'python(\d+(\.\d+)*)?$', Path(t).name):
                i += 1
                if i < len(toks) and toks[i] == '-m': i += 2
                continue
            cur = str(self.current_script)
            if Path(t).name == Path(cur).name or t == cur:
                i += 1; continue
            cleaned.append(t); i += 1

        if not cleaned:
            QMessageBox.information(self, '引数なし', '貼り付けテキストから引数が抽出できませんでした。')
        else:
            def guess_type(val: str) -> str:
                if val.lower() in ('true', 'yes', 'on', 'false', 'no', 'off'): return 'flag'
                if re.fullmatch(r'[+-]?\d+', val): return 'int'
                if re.fullmatch(r'[+-]?\d+\.\d+', val): return 'float'
                return 'str'

            pos_idx = 0; j = 0; n = len(cleaned)
            while j < n:
                token = cleaned[j]
                if token.startswith('-'):
                    info = opt_info.get(token)
                    if info and info.get('type', 'str') == 'flag':
                        typ, val = 'flag', True
                        row = self._row_index_by_name(token)
                        if row >= 0: self._set_row(row, typ, val, enabled=True)
                        else: self.add_arg_row({'enabled': True, 'name': token, 'type': typ, 'value': val})
                        j += 1; continue

                    typ = info.get('type', 'str') if info else 'str'
                    if typ.startswith('list'):
                        vals: List[str] = []; k = j + 1
                        while k < n and not cleaned[k].startswith('-'):
                            vals.append(cleaned[k]); k += 1
                        row = self._row_index_by_name(token)
                        if row >= 0: self._set_row(row, typ, vals, enabled=True)
                        else: self.add_arg_row({'enabled': True, 'name': token, 'type': typ, 'value': vals})
                        j = k
                    else:
                        if j + 1 < n and not cleaned[j + 1].startswith('-'):
                            val = cleaned[j + 1]
                            if info is None: typ = guess_type(val)
                            row = self._row_index_by_name(token)
                            if row >= 0: self._set_row(row, typ, val, enabled=True)
                            else: self.add_arg_row({'enabled': True, 'name': token, 'type': typ, 'value': val})
                            j += 2
                        else:
                            row = self._row_index_by_name(token)
                            if row >= 0: self._set_row(row, typ, '', enabled=True)
                            else: self.add_arg_row({'enabled': True, 'name': token, 'type': typ, 'value': ''})
                            j += 1
                else:
                    name = positional_names[pos_idx] if pos_idx < len(positional_names) else token
                    typ = guess_type(token)
                    if typ == 'flag': typ = 'str'
                    row = self._row_index_by_name(name)
                    if row >= 0: self._set_row(row, typ, token, enabled=True)
                    else: self.add_arg_row({'enabled': True, 'name': name, 'type': typ, 'value': token})
                    pos_idx += 1; j += 1

            self.update_command_preview()
            QMessageBox.information(self, '取り込み完了', '貼り付けテキストを反映しました（該当引数のみ有効化）。')

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
