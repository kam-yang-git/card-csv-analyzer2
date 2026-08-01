# -*- coding: utf-8 -*-
"""
gui.py
------
Tkinter の画面まわり。起動エントリでもある。
ボタン操作などはここ、重い処理の中身は main.py 経由で呼び出す。
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib import pyplot as plt

import main as app


class App(tk.Tk):
    """アプリ本体ウィンドウ。タブをまとめて起動時に中央配置する。"""
    def __init__(self) -> None:
        """ウィンドウを初期化し、DB準備と画面構築を行う。"""
        super().__init__()
        self.title("カード明細CSVアナライザ")
        self.geometry("1100x800")
        self.minsize(900, 600)

        app.initialize()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._center_window)

    def _center_window(self) -> None:
        """画面の上下左右中央へウィンドウを移す。"""
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _build(self) -> None:
        """タブを作ってノートブックに載せる。"""
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 各タブ（Frame）。on_changed / on_registered でタブ間の再読込をつなぐ
        self.merge_tab = MergeTab(notebook)
        self.tx_tab = TransactionsTab(notebook)
        self.profile_tab = ProfileTab(notebook, on_changed=self.merge_tab.refresh_profiles)
        self.alias_tab = AliasTab(notebook, on_reapplied=self.tx_tab.reload)
        self.unreg_tab = UnregisteredTab(notebook, on_registered=self.alias_tab.reload)
        self.analyze_tab = AnalyzeTab(notebook)

        notebook.add(self.merge_tab, text="マージ")
        notebook.add(self.tx_tab, text="明細")
        notebook.add(self.profile_tab, text="プロファイル設定")
        notebook.add(self.alias_tab, text="店名辞書")
        notebook.add(self.unreg_tab, text="未登録店名")
        notebook.add(self.analyze_tab, text="分析")

        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.notebook = notebook

    def _on_tab_changed(self, _event=None) -> None:
        """タブ切替時に、必要な一覧を再読込する。"""
        tab = self.notebook.select()
        widget = self.nametowidget(tab)
        if widget is self.unreg_tab:
            self.unreg_tab.reload()
        elif widget is self.analyze_tab:
            self.analyze_tab.reload_filters()
        elif widget is self.merge_tab:
            self.merge_tab.refresh_profiles()
        elif widget is self.tx_tab:
            self.tx_tab.reload_filters(keep_selection=True)

    def _on_close(self) -> None:
        """ウィンドウ終了時に Matplotlib の Figure を解放してから終了する。"""
        self.analyze_tab.release_chart()
        plt.close("all")
        self.destroy()
        self.quit()


# ---------- マージ ----------

class MergeTab(ttk.Frame):
    """「マージ」タブ。CSV追加・プロファイル割当・検証・マージ実行。"""
    def __init__(self, master) -> None:
        """マージ対象ファイル一覧などを初期化する。"""
        super().__init__(master)
        self.files: list[dict[str, Any]] = []  # 追加したCSV情報のリスト（path/profile/status等）
        self._busy = False  # マージ実行中なら True（二重実行防止）
        self._build()
        self.refresh_profiles()

    def _build(self) -> None:
        """ボタン・一覧・プロファイル割当UIを配置する。"""
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(top, text="伝票追加", command=self.add_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="選択削除", command=self.remove_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="すべて削除", command=self.clear_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="検証", command=self.validate_all).pack(side=tk.LEFT, padx=12)
        self.merge_btn = ttk.Button(top, text="マージ実行", command=self.run_merge)
        self.merge_btn.pack(side=tk.LEFT, padx=2)

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        cols = ("file", "profile", "status", "message")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("file", text="ファイル名")
        self.tree.heading("profile", text="プロファイル")
        self.tree.heading("status", text="状態")
        self.tree.heading("message", text="メッセージ")
        self.tree.column("file", width=260)
        self.tree.column("profile", width=180)
        self.tree.column("status", width=80)
        self.tree.column("message", width=360)
        scroll = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        assign = ttk.Frame(self)
        assign.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(assign, text="選択行のプロファイル:").pack(side=tk.LEFT)
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(
            assign, textvariable=self.profile_var, state="readonly", width=40
        )
        self.profile_combo.pack(side=tk.LEFT, padx=4)
        ttk.Button(assign, text="割当", command=self.assign_profile).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="準備完了")
        ttk.Label(self, textvariable=self.status_var).pack(fill=tk.X, padx=8, pady=8)

    def refresh_profiles(self) -> None:
        """有効なプロファイル一覧をコンボボックスへ反映する。"""
        profiles = app.list_profiles(enabled_only=True)
        names = [p["profile_name"] for p in profiles]
        self._profiles_by_name = {p["profile_name"]: p for p in profiles}
        self.profile_combo["values"] = names
        if names and self.profile_var.get() not in names:
            self.profile_var.set(names[0])
        # 既存割当の表示更新
        self._redraw()

    def add_files(self) -> None:
        """ファイル選択ダイアログで伝票CSVを追加する。"""
        paths = filedialog.askopenfilenames(
            title="伝票CSVを選択",
            filetypes=[("CSV", "*.csv"), ("すべて", "*.*")],
        )
        for p in paths:
            path = Path(p)
            if any(f["path"] == path for f in self.files):
                continue
            self.files.append(
                {
                    "path": path,
                    "profile_name": self.profile_var.get() or "",
                    "status": "未検証",
                    "message": "",
                }
            )
        self._redraw()

    def remove_selected(self) -> None:
        """一覧で選んだ行を削除する。"""
        selected = set(self.tree.selection())
        if not selected:
            return
        indices = [self.tree.index(i) for i in selected]
        for idx in sorted(indices, reverse=True):
            del self.files[idx]
        self._redraw()

    def clear_files(self) -> None:
        """一覧を空にする。"""
        self.files.clear()
        self._redraw()

    def assign_profile(self) -> None:
        """選択行に、コンボで選んだプロファイルを割り当てる。"""
        name = self.profile_var.get()
        if not name:
            messagebox.showwarning("確認", "プロファイルを選択してください")
            return
        for item in self.tree.selection():
            idx = self.tree.index(item)
            self.files[idx]["profile_name"] = name
            self.files[idx]["status"] = "未検証"
            self.files[idx]["message"] = ""
        self._redraw()

    def _redraw(self) -> None:
        """内部リスト self.files の内容を Treeview に描き直す。"""
        self.tree.delete(*self.tree.get_children())
        for f in self.files:
            self.tree.insert(
                "",
                tk.END,
                values=(f["path"].name, f["profile_name"], f["status"], f["message"]),
            )

    def _resolve_jobs(self) -> list[tuple[Path, dict[str, Any]]] | None:
        """マージ／検証用に (パス, プロファイル) のリストを作る。不足なら None。"""
        if not self.files:
            messagebox.showwarning("確認", "伝票ファイルを追加してください")
            return None
        jobs = []
        for f in self.files:
            profile = self._profiles_by_name.get(f["profile_name"])
            if not profile:
                messagebox.showerror(
                    "エラー",
                    f"プロファイル未割当: {f['path'].name}",
                )
                return None
            jobs.append((f["path"], profile))
        return jobs

    def validate_all(self) -> None:
        """一覧の全ファイルを検証し、状態列を更新する。"""
        jobs = self._resolve_jobs()
        if jobs is None:
            return
        for f, (_path, profile) in zip(self.files, jobs):
            ok, msg, _count = app.validate_file(f["path"], profile)
            f["status"] = "検証OK" if ok else "エラー"
            f["message"] = msg
        self._redraw()

    def run_merge(self) -> None:
        """別スレッドでマージを実行し、画面を固まらせない。"""
        if self._busy:
            return
        jobs = self._resolve_jobs()
        if jobs is None:
            return

        self._busy = True
        self.merge_btn.configure(state=tk.DISABLED)
        self.status_var.set("マージ実行中…")

        def worker() -> None:
            result = app.merge_files(jobs, progress=lambda m: self.after(0, self.status_var.set, m))
            self.after(0, lambda: self._on_merge_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_merge_done(self, result) -> None:
        """マージ完了後に結果ダイアログを出す（メインスレッド側）。"""
        self._busy = False
        self.merge_btn.configure(state=tk.NORMAL)
        if not result.ok:
            self.status_var.set("マージ失敗")
            messagebox.showerror("エラー", app.MSG_ERROR_)
            return

        self.status_var.set(
            f"完了: 登録{result.inserted_rows}件 / スキップ{result.skipped_rows}件 / "
            f"除外{result.excluded_rows}件 / 未登録店名{result.unregistered_count}件"
        )
        messagebox.showinfo(
            "完了",
            f"マージが完了しました。\n\n"
            f"処理明細: {result.merged_rows} 件\n"
            f"新規登録: {result.inserted_rows} 件\n"
            f"重複スキップ: {result.skipped_rows} 件\n"
            f"除外行: {result.excluded_rows} 件\n"
            f"未登録店名: {result.unregistered_count} 件",
        )
        if result.has_exclusions:
            messagebox.showwarning("除外行", app.MSG_EXCLUDED_)


# ---------- 明細 ----------

class TransactionsTab(ttk.Frame):
    """「明細」タブ。蓄積明細の閲覧・分類編集・バックアップ／リストア。"""

    def __init__(self, master) -> None:
        super().__init__(master)
        self.rows: list[dict[str, Any]] = []
        self._build()
        self.reload_filters()

    def _build(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text="期間").grid(row=0, column=0, sticky=tk.W)
        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        self.from_combo = ttk.Combobox(top, textvariable=self.from_var, width=12, state="readonly")
        self.to_combo = ttk.Combobox(top, textvariable=self.to_var, width=12, state="readonly")
        self.from_combo.grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Label(top, text="〜").grid(row=0, column=2)
        self.to_combo.grid(row=0, column=3, sticky=tk.W, padx=4)

        ttk.Label(top, text="カード会社").grid(row=1, column=0, sticky=tk.W, pady=4)
        self.company_var = tk.StringVar(value="すべて")
        self.company_combo = ttk.Combobox(
            top, textvariable=self.company_var, width=20, state="readonly"
        )
        self.company_combo.grid(row=1, column=1, sticky=tk.W, padx=4)

        ttk.Label(top, text="分類").grid(row=1, column=2, sticky=tk.W)
        self.filter_category_var = tk.StringVar(value="すべて")
        self.filter_category_combo = ttk.Combobox(
            top,
            textvariable=self.filter_category_var,
            values=["すべて", *app.CATEGORIES_],
            width=12,
            state="readonly",
        )
        self.filter_category_combo.grid(row=1, column=3, sticky=tk.W, padx=4)

        ttk.Button(top, text="表示更新", command=self.reload).grid(
            row=0, column=4, rowspan=2, padx=12
        )

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        cols = (
            "date",
            "merchant",
            "normalized",
            "category",
            "amount",
            "company",
            "manual",
            "file",
            "line",
        )
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, h, w in [
            ("date", "利用年月日", 100),
            ("merchant", "利用店名", 160),
            ("normalized", "正規化店名", 140),
            ("category", "分類", 70),
            ("amount", "利用金額", 90),
            ("company", "カード会社", 110),
            ("manual", "分類手動", 70),
            ("file", "取込元ファイル", 140),
            ("line", "行", 50),
        ]:
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w)
        scroll = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        form = ttk.Frame(self)
        form.pack(fill=tk.X, padx=8, pady=4)
        ttk.Label(form, text="選択行の分類:").pack(side=tk.LEFT)
        self.edit_category_var = tk.StringVar(value=app.CATEGORIES_[0])
        ttk.Combobox(
            form,
            textvariable=self.edit_category_var,
            values=list(app.CATEGORIES_),
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(form, text="分類を変更", command=self.apply_category).pack(
            side=tk.LEFT, padx=4
        )
        self.count_var = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.count_var).pack(side=tk.RIGHT)

        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(bottom, text="CSVバックアップ", command=self.backup_csv).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(bottom, text="CSVリストア", command=self.restore_csv).pack(
            side=tk.LEFT, padx=4
        )

    def reload_filters(self, keep_selection: bool = False) -> None:
        """フィルタ候補を更新し、一覧を再読込する。"""
        months = app.transaction_year_months()
        companies = ["すべて", *app.transaction_card_companies()]
        self.from_combo["values"] = months
        self.to_combo["values"] = months
        self.company_combo["values"] = companies
        if months:
            if not keep_selection or self.from_var.get() not in months:
                self.from_var.set(months[0])
            if not keep_selection or self.to_var.get() not in months:
                self.to_var.set(months[-1])
        else:
            self.from_var.set("")
            self.to_var.set("")
        if self.company_var.get() not in companies:
            self.company_var.set("すべて")
        self.reload()

    def reload(self) -> None:
        """フィルタ条件で明細一覧を読み直す。"""
        self.rows = app.list_transactions(
            year_month_from=self.from_var.get() or None,
            year_month_to=self.to_var.get() or None,
            card_company=self.company_var.get(),
            category=self.filter_category_var.get(),
        )
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            self.tree.insert(
                "",
                tk.END,
                iid=str(r["id"]),
                values=(
                    r["利用年月日"],
                    r["利用店名"],
                    r["正規化店名"],
                    r["分類"],
                    f"{int(r['利用金額']):,}",
                    r["カード会社"],
                    "はい" if r["分類手動"] else "いいえ",
                    r["取込元ファイル名"],
                    r["取込行番号"],
                ),
            )
        total = app.count_transactions()
        self.count_var.set(f"表示 {len(self.rows)} 件 / 全 {total} 件")

    def apply_category(self) -> None:
        """選択行の分類を手修正する。"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("確認", "明細を選択してください")
            return
        tx_id = int(sel[0])
        category = self.edit_category_var.get()
        try:
            app.update_transaction_category(tx_id, category)
            self.reload()
            self.tree.selection_set(str(tx_id))
            messagebox.showinfo("完了", "分類を変更しました（手修正）")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))

    def backup_csv(self) -> None:
        """全明細をバックアップCSVへ書き出す。"""
        path = filedialog.asksaveasfilename(
            title="明細バックアップの保存先",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("すべて", "*.*")],
            initialfile="transactions_backup.csv",
        )
        if not path:
            return
        try:
            count = app.export_transactions_csv(path)
            messagebox.showinfo("完了", f"{count} 件をバックアップしました。\n{path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))

    def restore_csv(self) -> None:
        """バックアップCSVで明細を差し替え復元する。"""
        if not messagebox.askyesno(
            "確認",
            "既存の明細をすべて削除し、CSVの内容で復元します。\nよろしいですか？",
        ):
            return
        path = filedialog.askopenfilename(
            title="明細バックアップCSVを選択",
            filetypes=[("CSV", "*.csv"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            count = app.restore_transactions_csv(path)
            self.reload_filters()
            messagebox.showinfo("完了", f"{count} 件を復元しました。")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))


# ---------- プロファイル ----------

class ProfileTab(ttk.Frame):
    """「プロファイル設定」タブ。伝票形式の登録・編集・テスト読込。"""
    def __init__(self, master, on_changed=None) -> None:
        """on_changed は保存後にマージタブへ通知するコールバック。"""
        super().__init__(master)
        self.on_changed = on_changed
        self.current_id: int | None = None  # 編集中プロファイルのID（新規は None）
        self._build()
        self.reload()

    def _build(self) -> None:
        """左に一覧、右に入力フォームを置く。"""
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=2)

        self.listbox = tk.Listbox(left, exportselection=False)
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=4)
        for text, cmd in [
            ("新規", self.new_profile),
            ("複製", self.duplicate),
            ("保存", self.save),
            ("無効化", self.disable),
            ("削除", self.delete),
            ("テスト読込", self.test_read),
        ]:
            ttk.Button(btns, text=text, command=cmd).pack(side=tk.LEFT, padx=2, pady=2)

        form = ttk.Frame(right)
        form.pack(fill=tk.BOTH, expand=True)
        self.vars = {
            "profile_name": tk.StringVar(),
            "card_company": tk.StringVar(),
            "encoding": tk.StringVar(value="cp932"),
            "header_row": tk.StringVar(value="1"),
            "footer_rows": tk.StringVar(value="0"),
            "date_column": tk.StringVar(),
            "merchant_column": tk.StringVar(),
            "amount_column": tk.StringVar(),
            "date_format": tk.StringVar(value="%Y/%m/%d"),
            "thousands_separator": tk.StringVar(value=","),
            "currency_symbol": tk.StringVar(value=""),
            "minus_format": tk.StringVar(value="sign"),
            "enabled": tk.BooleanVar(value=True),
        }

        rows = [
            ("プロファイル名", "profile_name", None),
            ("カード会社名", "card_company", None),
            ("文字コード", "encoding", list(app.ENCODING_CANDIDATES_)),
            ("ヘッダー行(1始まり)", "header_row", None),
            ("末尾不要行数", "footer_rows", None),
            ("日付列名", "date_column", None),
            ("店名列名", "merchant_column", None),
            ("金額列名", "amount_column", None),
            ("日付書式", "date_format", list(app.DATE_FORMAT_CANDIDATES_)),
            ("桁区切り", "thousands_separator", [",", ""]),
            ("通貨記号", "currency_symbol", ["", "¥", "￥", "円"]),
            ("マイナス表記", "minus_format", list(app.MINUS_FORMAT_CANDIDATES_)),
        ]
        for i, (label, key, values) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky=tk.W, pady=3, padx=4)
            if values is None:
                entry = ttk.Entry(form, textvariable=self.vars[key], width=40)
                entry.grid(row=i, column=1, sticky=tk.W, pady=3)
            else:
                combo = ttk.Combobox(form, textvariable=self.vars[key], values=values, width=37)
                combo.grid(row=i, column=1, sticky=tk.W, pady=3)
        ttk.Checkbutton(form, text="有効", variable=self.vars["enabled"]).grid(
            row=len(rows), column=1, sticky=tk.W, pady=6
        )
        ttk.Label(
            form,
            text="ヘッダー行はCSV上の行番号（1始まり）です。",
            foreground="#555",
        ).grid(row=len(rows) + 1, column=0, columnspan=2, sticky=tk.W, padx=4)

        self.preview = tk.Text(right, height=10, wrap=tk.NONE)
        self.preview.pack(fill=tk.BOTH, expand=True, pady=8)

    def reload(self) -> None:
        """DBからプロファイル一覧を読み直す。"""
        self.profiles = app.list_profiles(enabled_only=False)
        self.listbox.delete(0, tk.END)
        for p in self.profiles:
            mark = "" if p["enabled"] else " [無効]"
            self.listbox.insert(tk.END, f"{p['profile_name']}{mark}")

    def _on_select(self, _event=None) -> None:
        """一覧選択時、右フォームへ値を流し込む。"""
        sel = self.listbox.curselection()
        if not sel:
            return
        p = self.profiles[sel[0]]
        self.current_id = p["id"]
        self.vars["profile_name"].set(p["profile_name"])
        self.vars["card_company"].set(p["card_company"])
        self.vars["encoding"].set(p["encoding"])
        self.vars["header_row"].set(str(p["header_row"]))
        self.vars["footer_rows"].set(str(p["footer_rows"]))
        self.vars["date_column"].set(p["date_column"])
        self.vars["merchant_column"].set(p["merchant_column"])
        self.vars["amount_column"].set(p["amount_column"])
        self.vars["date_format"].set(p["date_format"])
        self.vars["thousands_separator"].set(p["thousands_separator"])
        self.vars["currency_symbol"].set(p["currency_symbol"])
        self.vars["minus_format"].set(p["minus_format"])
        self.vars["enabled"].set(bool(p["enabled"]))

    def _collect(self) -> dict[str, Any]:
        """フォームの入力値を保存用 dict にまとめる。"""
        data = {
            "profile_name": self.vars["profile_name"].get(),
            "card_company": self.vars["card_company"].get(),
            "encoding": self.vars["encoding"].get(),
            "header_row": int(self.vars["header_row"].get() or "1"),
            "footer_rows": int(self.vars["footer_rows"].get() or "0"),
            "date_column": self.vars["date_column"].get(),
            "merchant_column": self.vars["merchant_column"].get(),
            "amount_column": self.vars["amount_column"].get(),
            "date_format": self.vars["date_format"].get(),
            "thousands_separator": self.vars["thousands_separator"].get(),
            "currency_symbol": self.vars["currency_symbol"].get(),
            "minus_format": self.vars["minus_format"].get(),
            "enabled": 1 if self.vars["enabled"].get() else 0,
        }
        if self.current_id is not None:
            data["id"] = self.current_id
        return data

    def new_profile(self) -> None:
        """新規入力モードにする（IDをクリアして欄を空に近づける）。"""
        self.current_id = None
        self.listbox.selection_clear(0, tk.END)
        for key, var in self.vars.items():
            if isinstance(var, tk.BooleanVar):
                var.set(True)
            elif key == "encoding":
                var.set("cp932")
            elif key == "header_row":
                var.set("1")
            elif key == "footer_rows":
                var.set("0")
            elif key == "date_format":
                var.set("%Y/%m/%d")
            elif key == "thousands_separator":
                var.set(",")
            elif key == "minus_format":
                var.set("sign")
            else:
                var.set("")

    def save(self) -> None:
        """フォーム内容をDBへ保存する。"""
        try:
            self.current_id = app.save_profile(self._collect())
            self.reload()
            if self.on_changed:
                self.on_changed()
            messagebox.showinfo("保存", "プロファイルを保存しました")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))

    def duplicate(self) -> None:
        """選択中プロファイルを別名で複製する。"""
        if self.current_id is None:
            messagebox.showwarning("確認", "複製元を選択してください")
            return
        name = simpledialog.askstring("複製", "新しいプロファイル名")
        if not name:
            return
        try:
            self.current_id = app.duplicate_profile(self.current_id, name)
            self.reload()
            if self.on_changed:
                self.on_changed()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))

    def disable(self) -> None:
        """選択中プロファイルを無効化する。"""
        if self.current_id is None:
            return
        app.set_profile_enabled(self.current_id, False)
        self.vars["enabled"].set(False)
        self.reload()
        if self.on_changed:
            self.on_changed()

    def delete(self) -> None:
        """選択中プロファイルを削除する。"""
        if self.current_id is None:
            return
        if not messagebox.askyesno("確認", "このプロファイルを削除しますか？"):
            return
        app.delete_profile(self.current_id)
        self.current_id = None
        self.reload()
        if self.on_changed:
            self.on_changed()

    def test_read(self) -> None:
        """サンプルCSVを読み、変換結果の先頭をプレビュー表示する。"""
        path = filedialog.askopenfilename(
            title="テスト用CSV",
            filetypes=[("CSV", "*.csv"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            profile = self._collect()
            df = app.preview_csv(path, profile, limit=20)
            self.preview.delete("1.0", tk.END)
            self.preview.insert(tk.END, df.to_string(index=False))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))


# ---------- 店名辞書 ----------

class AliasTab(ttk.Frame):
    """「店名辞書」タブ。分析用名称と既定分類の管理。"""
    def __init__(self, master, on_reapplied=None) -> None:
        """店名辞書タブを初期化する。"""
        super().__init__(master)
        self.on_reapplied = on_reapplied
        self.current_id: int | None = None
        self._build()
        self.reload()

    def _build(self) -> None:
        """検索・一覧・編集フォームを配置する。"""
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(top, text="検索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.search_var, width=30).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="検索", command=self.reload).pack(side=tk.LEFT)
        ttk.Button(top, text="追加", command=self.new_item).pack(side=tk.LEFT, padx=8)
        ttk.Button(top, text="保存", command=self.save).pack(side=tk.LEFT)
        ttk.Button(top, text="削除", command=self.delete).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="辞書を明細へ再適用", command=self.reapply).pack(
            side=tk.LEFT, padx=12
        )

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=8)
        cols = ("original", "lookup", "normalized", "category", "enabled")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings")
        headings = {
            "original": "原文",
            "lookup": "照合キー",
            "normalized": "分析用名称",
            "category": "既定分類",
            "enabled": "有効",
        }
        for c, h in headings.items():
            self.tree.heading(c, text=h)
            self.tree.column(c, width=160)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form = ttk.Frame(self)
        form.pack(fill=tk.X, padx=8, pady=8)
        self.original_var = tk.StringVar()
        self.lookup_var = tk.StringVar()
        self.normalized_var = tk.StringVar()
        self.category_var = tk.StringVar(value=app.CATEGORIES_[-1])
        self.enabled_var = tk.BooleanVar(value=True)
        self.notes_var = tk.StringVar()

        grid = [
            ("原文", self.original_var, False),
            ("照合キー", self.lookup_var, True),
            ("分析用名称", self.normalized_var, False),
            ("備考", self.notes_var, False),
        ]
        for i, (label, var, readonly) in enumerate(grid):
            ttk.Label(form, text=label).grid(row=0, column=i * 2, sticky=tk.W, padx=2)
            state = "readonly" if readonly else "normal"
            ttk.Entry(form, textvariable=var, width=22, state=state).grid(
                row=0, column=i * 2 + 1, padx=2
            )
        ttk.Label(form, text="既定分類").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Combobox(
            form,
            textvariable=self.category_var,
            values=list(app.CATEGORIES_),
            state="readonly",
            width=20,
        ).grid(row=1, column=1, sticky=tk.W)
        ttk.Checkbutton(form, text="有効", variable=self.enabled_var).grid(
            row=1, column=3, sticky=tk.W
        )
        self.original_var.trace_add("write", self._update_lookup)

    def _update_lookup(self, *_args) -> None:
        """新規入力中は、原文から照合キーを自動生成する。"""
        if self.current_id is None:
            self.lookup_var.set(app.make_lookup_key_(self.original_var.get()))

    def reload(self) -> None:
        """検索条件つきで辞書一覧を読み直す。"""
        self.rows = app.list_merchant_aliases(self.search_var.get())
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            self.tree.insert(
                "",
                tk.END,
                iid=str(r["id"]),
                values=(
                    r["original_name"],
                    r["lookup_key"],
                    r["normalized_name"],
                    r["default_category"],
                    "はい" if r["enabled"] else "いいえ",
                ),
            )

    def _on_select(self, _event=None) -> None:
        """一覧選択時、下の編集欄へ値を入れる。"""
        sel = self.tree.selection()
        if not sel:
            return
        alias_id = int(sel[0])
        row = next(r for r in self.rows if r["id"] == alias_id)
        self.current_id = alias_id
        self.original_var.set(row["original_name"])
        self.lookup_var.set(row["lookup_key"])
        self.normalized_var.set(row["normalized_name"])
        self.category_var.set(row["default_category"])
        self.enabled_var.set(bool(row["enabled"]))
        self.notes_var.set(row.get("notes") or "")

    def new_item(self) -> None:
        """新規登録モードにする。"""
        self.current_id = None
        self.tree.selection_remove(self.tree.selection())
        self.original_var.set("")
        self.lookup_var.set("")
        self.normalized_var.set("")
        self.category_var.set(app.CATEGORIES_[-1])
        self.enabled_var.set(True)
        self.notes_var.set("")

    def save(self) -> None:
        """編集欄の内容を店名辞書へ保存する。"""
        data = {
            "original_name": self.original_var.get(),
            "lookup_key": self.lookup_var.get() or app.make_lookup_key_(self.original_var.get()),
            "normalized_name": self.normalized_var.get() or self.original_var.get(),
            "default_category": self.category_var.get(),
            "notes": self.notes_var.get(),
            "enabled": 1 if self.enabled_var.get() else 0,
        }
        if self.current_id is not None:
            data["id"] = self.current_id
        try:
            self.current_id = app.save_merchant_alias(data)
            self.reload()
            messagebox.showinfo("保存", "店名辞書を保存しました")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))

    def delete(self) -> None:
        """選択中の辞書エントリを削除する。"""
        if self.current_id is None:
            return
        if not messagebox.askyesno("確認", "削除しますか？"):
            return
        app.delete_merchant_alias(self.current_id)
        self.current_id = None
        self.reload()

    def reapply(self) -> None:
        """店名辞書を手修正以外の明細へ再適用する。"""
        if not messagebox.askyesno(
            "確認",
            "店名辞書を明細へ再適用します。\n"
            "分類を手修正した明細は変更しません。\nよろしいですか？",
        ):
            return
        try:
            updated = app.reapply_merchant_aliases()
            if self.on_reapplied:
                self.on_reapplied()
            messagebox.showinfo("完了", f"{updated} 件の明細を更新しました")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))


# ---------- 未登録店名 ----------

class UnregisteredTab(ttk.Frame):
    """「未登録店名」タブ。辞書に無い店を選んで登録する。"""
    def __init__(self, master, on_registered=None) -> None:
        """on_registered は辞書登録後に店名辞書タブを更新する。"""
        super().__init__(master)
        self.on_registered = on_registered
        self._build()
        self.reload()

    def _build(self) -> None:
        """未登録一覧と、登録用の名称・分類入力欄を置く。"""
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(top, text="再読込", command=self.reload).pack(side=tk.LEFT)
        ttk.Button(top, text="辞書に登録", command=self.register_selected).pack(
            side=tk.LEFT, padx=8
        )

        mid = ttk.Frame(self)
        mid.pack(fill=tk.BOTH, expand=True, padx=8)
        cols = ("original", "lookup", "count", "company", "file")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        for c, h, w in [
            ("original", "原文", 220),
            ("lookup", "照合キー", 220),
            ("count", "出現回数", 80),
            ("company", "最終カード会社", 140),
            ("file", "最終ファイル", 200),
        ]:
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w)
        self.tree.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(self)
        form.pack(fill=tk.X, padx=8, pady=8)
        ttk.Label(form, text="分析用名称").pack(side=tk.LEFT)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var, width=30).pack(side=tk.LEFT, padx=4)
        ttk.Label(form, text="分類").pack(side=tk.LEFT, padx=(12, 0))
        self.category_var = tk.StringVar(value="変動費")
        ttk.Combobox(
            form,
            textvariable=self.category_var,
            values=list(app.CATEGORIES_),
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT, padx=4)

    def reload(self) -> None:
        """未登録店名一覧をDBから読み直す。"""
        self.rows = app.list_unregistered_merchants()
        self.tree.delete(*self.tree.get_children())
        for r in self.rows:
            self.tree.insert(
                "",
                tk.END,
                iid=r["lookup_key"],
                values=(
                    r["sample_original_name"],
                    r["lookup_key"],
                    r["occurrence_count"],
                    r["last_card_company"],
                    r["last_source_file"],
                ),
            )

    def register_selected(self) -> None:
        """選択行を、入力した分析用名称・分類で辞書登録する。"""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("確認", "登録する行を選択してください")
            return
        name = self.name_var.get().strip()
        category = self.category_var.get()
        if not name:
            messagebox.showwarning("確認", "分析用名称を入力してください")
            return
        try:
            for key in selected:
                row = next(r for r in self.rows if r["lookup_key"] == key)
                app.register_unregistered_as_alias(
                    lookup_key=row["lookup_key"],
                    original_name=row["sample_original_name"],
                    normalized_name=name,
                    category=category,
                )
            self.reload()
            if self.on_registered:
                self.on_registered()
            messagebox.showinfo("完了", "店名辞書へ登録しました")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("エラー", str(exc))


# ---------- 分析 ----------

class AnalyzeTab(ttk.Frame):
    """「分析」タブ。分類の円グラフと集計表。"""
    def __init__(self, master) -> None:
        """分析タブを初期化する。"""
        super().__init__(master)
        self.df = None  # DBから読み込んだ明細（DataFrame）
        self.result = None  # 直近の集計結果（AnalysisResult）
        self.canvas = None  # 円グラフを貼る Matplotlib キャンバス
        self._build()
        self.reload_filters()

    def _build(self) -> None:
        """条件欄・円グラフ領域・集計表・保存ボタンを配置する。"""
        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=8)

        ttk.Label(top, text="期間").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.from_var = tk.StringVar()
        self.to_var = tk.StringVar()
        self.from_combo = ttk.Combobox(top, textvariable=self.from_var, width=12, state="readonly")
        self.to_combo = ttk.Combobox(top, textvariable=self.to_var, width=12, state="readonly")
        self.from_combo.grid(row=0, column=1, sticky=tk.W, padx=4)
        ttk.Label(top, text="〜").grid(row=0, column=2)
        self.to_combo.grid(row=0, column=3, sticky=tk.W, padx=4)

        ttk.Label(top, text="カード会社").grid(row=1, column=0, sticky=tk.W)
        self.company_var = tk.StringVar(value="すべて")
        self.company_combo = ttk.Combobox(
            top, textvariable=self.company_var, width=20, state="readonly"
        )
        self.company_combo.grid(row=1, column=1, sticky=tk.W, padx=4, pady=4)

        ttk.Label(top, text="分類").grid(row=1, column=2, sticky=tk.W)
        self.category_var = tk.StringVar(value="すべて")
        self.category_combo = ttk.Combobox(
            top,
            textvariable=self.category_var,
            values=["すべて", *app.CATEGORIES_],
            width=12,
            state="readonly",
        )
        self.category_combo.grid(row=1, column=3, sticky=tk.W, padx=4)

        self.include_negative = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top, text="返金・取消（マイナス金額）を含める", variable=self.include_negative
        ).grid(row=2, column=1, columnspan=2, sticky=tk.W, pady=4)

        ttk.Button(top, text="集計実行", command=self.run_analyze).grid(
            row=2, column=3, sticky=tk.E, padx=4
        )

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.chart_frame = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(self.chart_frame, weight=3)
        body.add(right, weight=2)

        cols = ("category", "amount", "count", "ratio")
        self.tree = ttk.Treeview(right, columns=cols, show="headings", height=12)
        for c, h, w in [
            ("category", "分類", 80),
            ("amount", "合計", 100),
            ("count", "件数", 60),
            ("ratio", "割合", 80),
        ]:
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.summary_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.summary_var).pack(anchor=tk.W, pady=4)

        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(bottom, text="円グラフをPNG保存", command=self.save_png).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(bottom, text="集計結果をCSV保存", command=self.save_csv).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(bottom, text="明細をCSV出力", command=self.save_detail).pack(
            side=tk.LEFT, padx=4
        )

    def reload_filters(self) -> None:
        """DB明細を読み、期間やカード会社の候補を更新する。"""
        self.df = app.load_transactions_df()
        months = app.available_year_months(self.df)
        companies = ["すべて", *app.available_card_companies(self.df)]
        self.from_combo["values"] = months
        self.to_combo["values"] = months
        self.company_combo["values"] = companies
        if months:
            self.from_var.set(months[0])
            self.to_var.set(months[-1])
        else:
            self.from_var.set("")
            self.to_var.set("")
        self.company_var.set("すべて")

    def run_analyze(self) -> None:
        """条件どおりに集計し、表と円グラフを更新する。"""
        self.df = app.load_transactions_df()
        if self.df is None or self.df.empty:
            messagebox.showwarning("確認", "分析対象の明細がありません")
            return
        # 前回の円グラフ Figure を閉じないとプロセスが残ることがある
        self.release_chart()
        self.result = app.analyze(
            self.df,
            year_month_from=self.from_var.get() or None,
            year_month_to=self.to_var.get() or None,
            card_company=self.company_var.get(),
            category=self.category_var.get(),
            include_negative=self.include_negative.get(),
        )
        self._show_result()

    def release_chart(self) -> None:
        """円グラフのキャンバスと Matplotlib Figure を解放する。"""
        if self.canvas is not None:
            self.canvas.get_tk_widget().destroy()
            self.canvas = None
        if self.result is not None and self.result.figure is not None:
            plt.close(self.result.figure)

    def _show_result(self) -> None:
        """AnalysisResult を画面の表とグラフへ反映する。"""
        assert self.result is not None
        self.tree.delete(*self.tree.get_children())
        for row in self.result.summary.itertuples():
            self.tree.insert(
                "",
                tk.END,
                values=(
                    row.分類,
                    f"{int(row.利用金額合計):,}",
                    int(row.明細件数),
                    row.割合,
                ),
            )
        self.tree.insert(
            "",
            tk.END,
            values=(
                "合計",
                f"{self.result.total_amount:,}",
                self.result.total_count,
                "100.00%",
            ),
        )
        self.summary_var.set(
            f"未分類: {self.result.uncategorized_count} 件 / "
            f"{self.result.uncategorized_amount:,} 円"
        )

        self.canvas = FigureCanvasTkAgg(self.result.figure, master=self.chart_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def save_csv(self) -> None:
        """分類集計CSVを results に保存する。"""
        if self.result is None:
            messagebox.showwarning("確認", "先に集計を実行してください")
            return
        path = app.save_summary_csv(
            self.result.summary, self.result.total_amount, self.result.total_count
        )
        messagebox.showinfo("保存", f"保存しました:\n{path}")

    def save_png(self) -> None:
        """円グラフPNGを results にPNG保存する。"""
        if self.result is None:
            messagebox.showwarning("確認", "先に集計を実行してください")
            return
        path = app.save_pie_png(self.result.figure)
        messagebox.showinfo("保存", f"保存しました:\n{path}")

    def save_detail(self) -> None:
        """フィルタ後明細をCSV保存する。"""
        if self.result is None:
            messagebox.showwarning("確認", "先に集計を実行してください")
            return
        path = filedialog.asksaveasfilename(
            title="明細CSVの保存先",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("すべて", "*.*")],
            initialfile="category_detail.csv",
        )
        if not path:
            return
        out = app.save_detail_csv(self.result.filtered_df, path)
        messagebox.showinfo("保存", f"保存しました:\n{out}")


def main() -> None:
    """アプリを起動する入口。"""
    app_ui = App()
    app_ui.mainloop()


if __name__ == "__main__":
    main()
