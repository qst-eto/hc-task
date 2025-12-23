
# PyScriptRunner (PySide6)

## 機能概要
- 指定フォルダから `.py` スクリプトを選び、GUIで引数を設定して実行
- `parse_args()` を AST解析して引数を自動取り込み（`nargs`/`type`/`default`/flag 対応）
- 引数プリセットの保存/読み込み（スクリプトごとに JSON）
- 実行コマンドの自動改行表示・コピーボタン
- 出力ペインはコンパクト、引数編集領域を広く確保

## セットアップ
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
``
