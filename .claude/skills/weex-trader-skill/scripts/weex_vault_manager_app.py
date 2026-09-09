#!/usr/bin/env python3
"""Vault manager UI for Windows/macOS interactive vault flows."""

from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path
from typing import Callable, Optional

from weex_agent_state import refresh_agent_records
from weex_gui_bootstrap import maybe_reexec_under_managed_gui_runtime
from weex_gui_launcher import SUPPORTED_VAULT_ACTIONS, maybe_detach_gui_entrypoint
from weex_profile_language import resolve_language


tk = None
tkfont = None
messagebox = None
simpledialog = None

ProfileError = RuntimeError
lock_linux_vault = None
reset_linux_vault = None
secure_store_backend_name = None
setup_linux_vault = None
unlock_linux_vault = None
vault_status = None

PALETTE = {
    "button_primary_bg": "#173257",
    "button_primary_active": "#112641",
    "button_primary_text": "#ffffff",
    "button_secondary_bg": "#eef2f7",
    "button_secondary_active": "#dde5ee",
    "button_secondary_text": "#1b3149",
    "button_danger_bg": "#fbeeee",
    "button_danger_active": "#f3d9d7",
    "button_danger_text": "#9f3b31",
    "button_disabled_bg": "#dce2ea",
    "button_disabled_text": "#7b8795",
    "button_focus": "#2c6496",
    "help_icon_bg": "#f7efe2",
    "help_icon_border": "#d5bf96",
    "help_icon_text": "#7d5922",
    "help_bubble_bg": "#fffdf8",
    "help_bubble_border": "#d9c8ab",
    "help_bubble_title": "#4d3920",
    "help_bubble_text": "#5b6674",
}


TEXTS = {
    "en": {
        "window_title": "WEEX Vault",
        "eyebrow": "GLOBAL VAULT",
        "title": "Shared Vault Access",
        "title_help": "Complete vault setup or unlock here before using private WEEX profile actions. This window controls the shared vault used by every saved profile.",
        "body": "Complete vault setup or unlock here before using private WEEX profile actions. You can also review the current state or lock the vault again from this window.",
        "request_setup": "Requested action: initialize the vault.",
        "request_unlock": "Requested action: unlock the vault.",
        "request_lock": "Requested action: focus the lock flow from this window.",
        "request_status": "Requested action: review the current vault state only.",
        "backend": "Secure backend",
        "backend_help": "Shows which local secure-storage backend is currently active for the shared application vault.",
        "backend_unavailable": "Application Vault (unavailable)",
        "scope": "Vault scope",
        "scope_value": "Shared by all profiles",
        "scope_help": "This vault is shared by every saved WEEX profile. Locking or resetting it affects all profile credentials.",
        "state": "Vault state",
        "state_help": "The vault can be uninitialized, unlocked, or locked. The current state determines which profile actions are available.",
        "guidance": "Next step",
        "guidance_help": "This guidance line explains the safest next action based on the current vault state.",
        "initialize": "Initialize Vault",
        "unlock": "Unlock Vault",
        "lock": "Lock Vault",
        "uninitialized": "Not initialized",
        "unlocked": "Unlocked ({mode})",
        "locked": "Locked ({mode})",
        "guidance_setup": "Initialize the vault here, then profile actions can read or save credentials.",
        "guidance_unlock": "Unlock the vault here, then profile actions can read or save credentials.",
        "guidance_ready": "Vault is ready. You can return to profile work or lock it again here.",
        "guidance_error": "Resolve the vault error before using private profile actions.",
        "guidance_reset": "If you forgot the passphrase, reset the vault here. This deletes all saved profiles.",
        "passphrase_title": "Vault Passphrase",
        "passphrase_prompt": "Enter the vault passphrase.",
        "passphrase_confirm_title": "Confirm Vault Passphrase",
        "passphrase_confirm_prompt": "Re-enter the vault passphrase.",
        "passphrase_empty": "Vault passphrase cannot be empty.",
        "passphrase_mismatch": "Vault passphrase confirmation did not match.",
        "reset": "Reset Vault",
        "reset_warning_title": "Reset Vault",
        "reset_warning_body": "Resetting the vault deletes all saved profiles, the default profile, and all stored secrets. This cannot be undone.",
        "reset_token_prompt": "Type RESET to continue.",
        "reset_token_mismatch": "Confirmation text did not match RESET.",
        "reset_success_title": "Vault Reset",
        "reset_success_body": "Vault reset complete. All saved profiles were removed and the vault returned to setup required.",
        "vault_ready_title": "Vault Ready",
        "vault_ready_body": "The application vault has been initialized and unlocked.",
        "vault_error_title": "Vault Error",
        "runtime_missing": "Unable to start the WEEX vault UI because Python dependency '{module_name}' is missing.",
        "runtime_unavailable": "Unable to start the WEEX vault UI because its runtime dependencies are unavailable.",
    },
    "zh": {
        "window_title": "WEEX Vault",
        "eyebrow": "GLOBAL VAULT",
        "title": "共享 Vault 访问",
        "title_help": "在进行私有 WEEX 账号操作前，请先在这里完成共享 Vault 的初始化或解锁。这个窗口控制所有已保存账号共用的 Vault。",
        "body": "请先在这里完成 Vault 初始化或解锁，再进行私有 WEEX 账号相关操作。你也可以在这个窗口里查看当前状态，或再次锁定 Vault。",
        "request_setup": "请求动作：初始化 Vault。",
        "request_unlock": "请求动作：解锁 Vault。",
        "request_lock": "请求动作：在这个窗口里聚焦到锁定流程。",
        "request_status": "请求动作：仅查看当前 Vault 状态。",
        "backend": "安全后端",
        "backend_help": "显示当前共享应用层 Vault 正在使用的本地安全存储后端。",
        "backend_unavailable": "Application Vault（不可用）",
        "scope": "Vault 范围",
        "scope_value": "所有账号共用",
        "scope_help": "这个 Vault 由所有已保存 WEEX 账号共用；锁定或重置都会影响全部账号凭证。",
        "state": "Vault 状态",
        "state_help": "Vault 可能处于未初始化、已解锁或已锁定状态；不同状态会决定 profile 操作是否可用。",
        "guidance": "下一步",
        "guidance_help": "这一行会根据当前 Vault 状态提示最安全、最直接的下一步操作。",
        "initialize": "初始化 Vault",
        "unlock": "解锁 Vault",
        "lock": "锁定 Vault",
        "uninitialized": "未初始化",
        "unlocked": "已解锁（{mode}）",
        "locked": "已锁定（{mode}）",
        "guidance_setup": "请先在这里初始化 Vault，之后 profile 操作才能读取或保存密钥。",
        "guidance_unlock": "请先在这里解锁 Vault，之后 profile 操作才能读取或保存密钥。",
        "guidance_ready": "Vault 已就绪。你现在可以回到 profile 工作流，也可以在这里再次锁定它。",
        "guidance_error": "请先解决 Vault 错误，再继续私有 profile 操作。",
        "guidance_reset": "如果忘记 Vault 密码，可在这里重置。该操作会删除所有已保存账号。",
        "passphrase_title": "Vault 密码",
        "passphrase_prompt": "请输入 Vault 密码。",
        "passphrase_confirm_title": "确认 Vault 密码",
        "passphrase_confirm_prompt": "请再次输入 Vault 密码。",
        "passphrase_empty": "Vault 密码不能为空。",
        "passphrase_mismatch": "两次输入的 Vault 密码不一致。",
        "reset": "重置 Vault",
        "reset_warning_title": "重置 Vault",
        "reset_warning_body": "重置 Vault 会删除所有已保存账号、默认账号和全部密钥，且无法恢复。",
        "reset_token_prompt": "请输入 RESET 继续。",
        "reset_token_mismatch": "确认文本不匹配 RESET。",
        "reset_success_title": "Vault 已重置",
        "reset_success_body": "Vault 已重置。所有已保存账号已删除，保险箱已回到未初始化状态。",
        "vault_ready_title": "Vault 已就绪",
        "vault_ready_body": "应用层 Vault 已初始化并解锁。",
        "vault_error_title": "Vault 错误",
        "runtime_missing": "无法启动 WEEX Vault UI，因为缺少 Python 依赖“{module_name}”。",
        "runtime_unavailable": "无法启动 WEEX Vault UI，因为运行时依赖不可用。",
    },
}


def _resolve_button_colors(kind: str) -> tuple[str, str, str]:
    if kind == "primary":
        return PALETTE["button_primary_bg"], PALETTE["button_primary_active"], PALETTE["button_primary_text"]
    if kind == "danger":
        return PALETTE["button_danger_bg"], PALETTE["button_danger_active"], PALETTE["button_danger_text"]
    return PALETTE["button_secondary_bg"], PALETTE["button_secondary_active"], PALETTE["button_secondary_text"]


class ActionButton:
    def __init__(
        self,
        parent: "tk.Widget",
        *,
        text: str,
        command: Callable[[], object] | None,
        kind: str,
        font: "tkfont.Font",
    ) -> None:
        self._command = command
        self._state = tk.NORMAL
        self._cursor = "hand2"
        self._hovered = False
        self._pressed = False
        self._focused = False
        self._set_kind(kind)

        self.widget = tk.Frame(
            parent,
            bg=self._base_bg,
            bd=0,
            highlightthickness=2,
            highlightbackground=self._base_bg,
            highlightcolor=self._base_bg,
            cursor=self._cursor,
            takefocus=1,
        )
        self._label = tk.Label(
            self.widget,
            text=text,
            font=font,
            bg=self._base_bg,
            fg=self._fg,
            bd=0,
            highlightthickness=0,
            cursor=self._cursor,
            padx=16,
            pady=10,
        )
        self._label.pack(fill=tk.BOTH, expand=True)

        for target in (self.widget, self._label):
            target.bind("<Enter>", self._on_enter)
            target.bind("<Leave>", self._on_leave)
            target.bind("<ButtonPress-1>", self._on_press)
            target.bind("<ButtonRelease-1>", self._on_release)
        self.widget.bind("<FocusIn>", self._on_focus_in)
        self.widget.bind("<FocusOut>", self._on_focus_out)
        self.widget.bind("<KeyPress-space>", self._on_space_press)
        self.widget.bind("<KeyRelease-space>", self._on_space_release)
        self.widget.bind("<Return>", self._on_return)
        self._apply_visual_state()

    def __getattr__(self, name: str) -> object:
        return getattr(self.widget, name)

    def grid(self, *args: object, **kwargs: object) -> object:
        return self.widget.grid(*args, **kwargs)

    def pack(self, *args: object, **kwargs: object) -> object:
        return self.widget.pack(*args, **kwargs)

    def configure(self, **kwargs: object) -> None:
        if "text" in kwargs:
            self._label.configure(text=str(kwargs.pop("text")))
        if "command" in kwargs:
            command = kwargs.pop("command")
            self._command = command if callable(command) else None
        if "state" in kwargs:
            self._state = str(kwargs.pop("state"))
            if self._state == tk.DISABLED:
                self._hovered = False
                self._pressed = False
                self._focused = False
        if "cursor" in kwargs:
            self._cursor = str(kwargs.pop("cursor"))
        if "kind" in kwargs:
            self._set_kind(str(kwargs.pop("kind")))
        if kwargs:
            self.widget.configure(**kwargs)
        self._apply_visual_state()

    config = configure

    def cget(self, key: str) -> object:
        if key == "text":
            return self._label.cget("text")
        if key == "state":
            return self._state
        if key == "cursor":
            return self._cursor
        if key == "kind":
            return self._kind
        return self.widget.cget(key)

    def invoke(self) -> object | None:
        if self._state == tk.DISABLED or self._command is None:
            return None
        return self._command()

    def _set_kind(self, kind: str) -> None:
        self._kind = kind
        self._base_bg, self._hover_bg, self._fg = _resolve_button_colors(kind)

    def _apply_visual_state(self) -> None:
        disabled = self._state == tk.DISABLED
        background = PALETTE["button_disabled_bg"] if disabled else (self._hover_bg if self._hovered or self._pressed else self._base_bg)
        foreground = PALETTE["button_disabled_text"] if disabled else self._fg
        cursor = "arrow" if disabled else self._cursor
        focus_ring = PALETTE["button_focus"] if self._focused and not disabled else background
        self.widget.configure(
            bg=background,
            cursor=cursor,
            highlightbackground=focus_ring,
            highlightcolor=focus_ring,
        )
        self._label.configure(bg=background, fg=foreground, cursor=cursor)

    def _on_enter(self, _event: object) -> None:
        if self._state == tk.DISABLED:
            return
        self._hovered = True
        self._apply_visual_state()

    def _on_leave(self, _event: object) -> None:
        self._hovered = False
        self._pressed = False
        self._apply_visual_state()

    def _on_press(self, _event: object) -> str | None:
        if self._state == tk.DISABLED:
            return "break"
        self.widget.focus_set()
        self._pressed = True
        self._apply_visual_state()
        return "break"

    def _on_release(self, _event: object) -> str | None:
        if self._state == tk.DISABLED:
            return "break"
        self._pressed = False
        self._apply_visual_state()
        if self._hovered:
            self.invoke()
        return "break"

    def _on_focus_in(self, _event: object) -> None:
        if self._state == tk.DISABLED:
            return
        self._focused = True
        self._apply_visual_state()

    def _on_focus_out(self, _event: object) -> None:
        self._focused = False
        self._pressed = False
        self._apply_visual_state()

    def _on_space_press(self, _event: object) -> str | None:
        if self._state == tk.DISABLED:
            return "break"
        self._pressed = True
        self._apply_visual_state()
        return "break"

    def _on_space_release(self, _event: object) -> str | None:
        if self._state == tk.DISABLED:
            return "break"
        was_pressed = self._pressed
        self._pressed = False
        self._apply_visual_state()
        if was_pressed:
            self.invoke()
        return "break"

    def _on_return(self, _event: object) -> str | None:
        if self._state == tk.DISABLED:
            return "break"
        self.invoke()
        return "break"


def _load_runtime_dependencies(language: str) -> None:
    global tk, tkfont, messagebox, simpledialog
    global ProfileError, lock_linux_vault, reset_linux_vault, secure_store_backend_name
    global setup_linux_vault, unlock_linux_vault, vault_status

    try:
        import tkinter as tk_module
        from tkinter import font as tkfont_module, messagebox as messagebox_module
        try:
            from tkinter import simpledialog as simpledialog_module
        except ImportError:
            simpledialog_module = types.SimpleNamespace(askstring=lambda *args, **kwargs: None)
    except ImportError as exc:
        raise SystemExit(TEXTS[language]["runtime_unavailable"]) from exc

    try:
        from weex_profile_store import (
            ProfileError as profile_error_type,
            lock_linux_vault as lock_linux_vault_fn,
            reset_linux_vault as reset_linux_vault_fn,
            secure_store_backend_name as secure_store_backend_name_fn,
            setup_linux_vault as setup_linux_vault_fn,
            unlock_linux_vault as unlock_linux_vault_fn,
            vault_status as vault_status_fn,
        )
    except ModuleNotFoundError as exc:
        module_name = exc.name or "unknown"
        raise SystemExit(TEXTS[language]["runtime_missing"].format(module_name=module_name)) from exc
    except ImportError as exc:
        raise SystemExit(TEXTS[language]["runtime_unavailable"]) from exc

    tk = tk_module
    tkfont = tkfont_module
    messagebox = messagebox_module
    simpledialog = simpledialog_module

    ProfileError = profile_error_type
    lock_linux_vault = lock_linux_vault_fn
    reset_linux_vault = reset_linux_vault_fn
    secure_store_backend_name = secure_store_backend_name_fn
    setup_linux_vault = setup_linux_vault_fn
    unlock_linux_vault = unlock_linux_vault_fn
    vault_status = vault_status_fn


class VaultManagerApp:
    def __init__(self, root: tk.Tk, language: str, requested_action: Optional[str]) -> None:
        self.root = root
        self.language = resolve_language(language)
        self.requested_action = (requested_action or "").strip() or None
        self.texts = TEXTS[self.language]
        self.backend_var = tk.StringVar(value=secure_store_backend_name())
        self.state_var = tk.StringVar(value="")
        self.guidance_var = tk.StringVar(value="")
        self.request_var = tk.StringVar(value=self._request_text())
        self.action_button: Optional[ActionButton] = None
        self.reset_button: Optional[ActionButton] = None
        self.current_state = "unknown"
        self.help_bubble = None
        self.help_bubble_key: Optional[tuple[str, str]] = None

        self.root.title(self.text("window_title"))
        self.root.geometry("760x420")
        self.root.minsize(700, 380)
        self.root.configure(bg="#edf1f6")
        self.fonts = self._build_fonts()
        self._build_layout()
        self.refresh_status()
        if self.requested_action in {"setup", "unlock"}:
            self.root.after(180, self._perform_requested_action)

    def text(self, key: str, **kwargs: object) -> str:
        value = self.texts[key]
        if kwargs:
            return value.format(**kwargs)
        return value

    def _request_text(self) -> str:
        if self.requested_action == "setup":
            return self.text("request_setup")
        if self.requested_action == "unlock":
            return self.text("request_unlock")
        if self.requested_action == "lock":
            return self.text("request_lock")
        if self.requested_action == "status":
            return self.text("request_status")
        return ""

    def _build_fonts(self) -> dict[str, object]:
        available = set(tkfont.families(self.root))

        def pick(*families: str) -> str:
            for family in families:
                if family in available:
                    return family
            return "TkDefaultFont"

        body_family = pick("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", "Helvetica Neue")
        display_family = pick("Bahnschrift", "Microsoft YaHei UI", "Segoe UI Semibold", "PingFang SC", body_family)
        mono_family = pick("Cascadia Mono", "Consolas", "JetBrains Mono", "Menlo", "Courier New")
        return {
            "eyebrow": tkfont.Font(family=body_family, size=10, weight="bold"),
            "title": tkfont.Font(family=display_family, size=24, weight="bold"),
            "section": tkfont.Font(family=display_family, size=13, weight="bold"),
            "label": tkfont.Font(family=body_family, size=10, weight="bold"),
            "body": tkfont.Font(family=body_family, size=10),
            "small": tkfont.Font(family=body_family, size=9),
            "mono": tkfont.Font(family=mono_family, size=9),
            "button": tkfont.Font(family=body_family, size=10, weight="bold"),
        }

    def _create_button(self, parent: tk.Widget, text: str, command: object, *, kind: str) -> ActionButton:
        return ActionButton(
            parent,
            text=text,
            command=command if callable(command) else None,
            kind=kind,
            font=self.fonts["button"],
        )

    def _hide_help_bubble(self) -> None:
        bubble = getattr(self, "help_bubble", None)
        if bubble is not None:
            try:
                bubble.destroy()
            except Exception:
                pass
        self.help_bubble = None
        self.help_bubble_key = None

    def _toggle_help_bubble(self, anchor: tk.Widget, title: str, body: str) -> str:
        cleaned_title = str(title or "").strip()
        cleaned_body = str(body or "").strip()
        if not cleaned_title and not cleaned_body:
            return "break"
        key = (cleaned_title, cleaned_body)
        if getattr(self, "help_bubble_key", None) == key and getattr(self, "help_bubble", None) is not None:
            self._hide_help_bubble()
            return "break"

        self._hide_help_bubble()
        bubble = tk.Frame(
            self.root,
            bg=PALETTE["help_bubble_bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=PALETTE["help_bubble_border"],
            padx=12,
            pady=10,
        )
        tk.Label(
            bubble,
            text=cleaned_title,
            bg=PALETTE["help_bubble_bg"],
            fg=PALETTE["help_bubble_title"],
            font=self.fonts["label"],
            justify=tk.LEFT,
            wraplength=280,
        ).pack(anchor=tk.W)
        tk.Label(
            bubble,
            text=cleaned_body,
            bg=PALETTE["help_bubble_bg"],
            fg=PALETTE["help_bubble_text"],
            font=self.fonts["small"],
            justify=tk.LEFT,
            wraplength=280,
        ).pack(anchor=tk.W, pady=(4, 0))
        bubble.lift()
        bubble.update_idletasks()

        try:
            anchor_x = max(12, anchor.winfo_rootx() - self.root.winfo_rootx() + anchor.winfo_width() + 8)
            anchor_y = max(12, anchor.winfo_rooty() - self.root.winfo_rooty())
            max_x = max(12, self.root.winfo_width() - bubble.winfo_reqwidth() - 12)
            max_y = max(12, self.root.winfo_height() - bubble.winfo_reqheight() - 12)
            if anchor_x > max_x:
                anchor_x = max(12, anchor.winfo_rootx() - self.root.winfo_rootx() - bubble.winfo_reqwidth() - 8)
            bubble.place(x=min(anchor_x, max_x), y=min(anchor_y, max_y))
        except Exception:
            bubble.place(relx=0.5, rely=0.5, anchor="center")

        bubble.bind("<Escape>", lambda _event: self._hide_help_bubble())
        self.help_bubble = bubble
        self.help_bubble_key = key
        return "break"

    def _create_help_icon(self, parent: tk.Widget, title: str, body: str, *, bg: str) -> tk.Label:
        icon = tk.Label(
            parent,
            text="?",
            bg=PALETTE["help_icon_bg"],
            fg=PALETTE["help_icon_text"],
            font=self.fonts["small"],
            bd=0,
            highlightthickness=1,
            highlightbackground=PALETTE["help_icon_border"],
            highlightcolor=PALETTE["help_icon_border"],
            cursor="hand2",
            padx=5,
            pady=0,
            takefocus=1,
        )
        icon.bind("<ButtonRelease-1>", lambda _event, widget=icon, popup_title=title, popup_body=body: self._toggle_help_bubble(widget, popup_title, popup_body))
        icon.bind("<Return>", lambda _event, widget=icon, popup_title=title, popup_body=body: self._toggle_help_bubble(widget, popup_title, popup_body))
        icon.bind("<KeyRelease-space>", lambda _event, widget=icon, popup_title=title, popup_body=body: self._toggle_help_bubble(widget, popup_title, popup_body))
        return icon

    def _pack_title_with_help(self, parent: tk.Widget, title: str, help_text: str, *, bg: str, fg: str, font: object) -> None:
        row = tk.Frame(parent, bg=bg)
        row.pack(anchor=tk.W, fill=tk.X)
        tk.Label(row, text=title, bg=bg, fg=fg, font=font).pack(side=tk.LEFT, anchor=tk.W)
        if str(help_text or "").strip():
            self._create_help_icon(row, title, help_text, bg=bg).pack(side=tk.LEFT, padx=(6, 0))

    def _grid_label_with_help(self, parent: tk.Widget, row: int, label: str, help_text: str, *, bg: str) -> None:
        label_row = tk.Frame(parent, bg=bg)
        label_row.grid(row=row, column=0, sticky="w")
        tk.Label(label_row, text=label, bg=bg, fg="#667687", font=self.fonts["small"]).pack(side=tk.LEFT, anchor=tk.W)
        if str(help_text or "").strip():
            self._create_help_icon(label_row, label, help_text, bg=bg).pack(side=tk.LEFT, padx=(6, 0))

    def _build_layout(self) -> None:
        shell = tk.Frame(self.root, bg="#edf1f6", padx=24, pady=24)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_columnconfigure(1, weight=0)

        left = tk.Frame(shell, bg="#edf1f6")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        tk.Label(left, text=self.text("eyebrow"), bg="#edf1f6", fg="#b78a48", font=self.fonts["eyebrow"]).pack(anchor=tk.W)
        title_row = tk.Frame(left, bg="#edf1f6")
        title_row.pack(anchor=tk.W, pady=(10, 10))
        self._pack_title_with_help(
            title_row,
            self.text("title"),
            self.text("title_help"),
            bg="#edf1f6",
            fg="#16263b",
            font=self.fonts["title"],
        )
        tk.Label(left, text=self.text("body"), bg="#edf1f6", fg="#667687", font=self.fonts["body"], wraplength=340, justify=tk.LEFT).pack(anchor=tk.W)
        if self.request_var.get():
            tk.Label(left, textvariable=self.request_var, bg="#edf1f6", fg="#173257", font=self.fonts["label"], wraplength=340, justify=tk.LEFT).pack(anchor=tk.W, pady=(16, 0))

        card = tk.Frame(shell, bg="#ffffff", highlightthickness=1, highlightbackground="#d7dee8", padx=18, pady=18)
        card.grid(row=0, column=1, sticky="ne")
        card.grid_columnconfigure(0, weight=1)
        self._grid_label_with_help(card, 0, self.text("backend"), self.text("backend_help"), bg="#ffffff")
        tk.Label(card, textvariable=self.backend_var, bg="#ffffff", fg="#16263b", font=self.fonts["body"], wraplength=300, justify=tk.LEFT).grid(row=1, column=0, sticky="w", pady=(4, 12))
        self._grid_label_with_help(card, 2, self.text("scope"), self.text("scope_help"), bg="#ffffff")
        tk.Label(card, text=self.text("scope_value"), bg="#ffffff", fg="#16263b", font=self.fonts["body"]).grid(row=3, column=0, sticky="w", pady=(4, 12))
        self._grid_label_with_help(card, 4, self.text("state"), self.text("state_help"), bg="#ffffff")
        tk.Label(card, textvariable=self.state_var, bg="#ffffff", fg="#16263b", font=self.fonts["body"]).grid(row=5, column=0, sticky="w", pady=(4, 12))
        self._grid_label_with_help(card, 6, self.text("guidance"), self.text("guidance_help"), bg="#ffffff")
        tk.Label(card, textvariable=self.guidance_var, bg="#ffffff", fg="#16263b", font=self.fonts["small"], wraplength=300, justify=tk.LEFT).grid(row=7, column=0, sticky="w", pady=(4, 16))

        button_row = tk.Frame(card, bg="#ffffff")
        button_row.grid(row=8, column=0, sticky="ew")
        button_row.grid_columnconfigure(0, weight=1)
        button_row.grid_columnconfigure(1, weight=1)
        self.action_button = self._create_button(button_row, self.text("unlock"), self.manage_vault, kind="primary")
        self.action_button.grid(row=0, column=0, sticky="ew")
        self.reset_button = self._create_button(button_row, self.text("reset"), self.reset_vault, kind="danger")
        self.reset_button.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self.reset_button.grid_remove()

    def _prompt_vault_passphrase(self, *, confirm: bool) -> Optional[str]:
        first = simpledialog.askstring(
            self.text("passphrase_title"),
            self.text("passphrase_prompt"),
            parent=self.root,
            show="*",
        )
        if first is None:
            return None
        first = first.strip()
        if not first:
            messagebox.showwarning(self.text("passphrase_title"), self.text("passphrase_empty"), parent=self.root)
            return None
        if not confirm:
            return first
        second = simpledialog.askstring(
            self.text("passphrase_confirm_title"),
            self.text("passphrase_confirm_prompt"),
            parent=self.root,
            show="*",
        )
        if second is None:
            return None
        if first != second.strip():
            messagebox.showerror(self.text("passphrase_title"), self.text("passphrase_mismatch"), parent=self.root)
            return None
        return first

    def _confirm_vault_reset(self) -> bool:
        confirmed = messagebox.askyesno(
            self.text("reset_warning_title"),
            self.text("reset_warning_body"),
            parent=self.root,
        )
        if not confirmed:
            return False
        token = simpledialog.askstring(
            self.text("reset_warning_title"),
            self.text("reset_token_prompt"),
            parent=self.root,
        )
        if token is None:
            return False
        if token.strip().upper() != "RESET":
            messagebox.showerror(self.text("reset_warning_title"), self.text("reset_token_mismatch"), parent=self.root)
            return False
        return True

    def refresh_status(self) -> None:
        try:
            status = vault_status()
        except ProfileError as exc:
            backend_text = self.text("backend_unavailable")
            state_text = str(exc)
            action_text = self.text("unlock")
            action_kind = "primary"
            guidance_text = self.text("guidance_error")
            self.current_state = "error"
        else:
            backend_text = str(status.get("backend") or secure_store_backend_name())
            state = str(status.get("state") or "unknown")
            mode = str(status.get("mode") or "manual_once")
            self.current_state = state
            if state == "uninitialized":
                state_text = self.text("uninitialized")
                action_text = self.text("initialize")
                action_kind = "primary"
                guidance_text = self.text("guidance_setup")
            elif state == "unlocked":
                state_text = self.text("unlocked", mode=mode)
                action_text = self.text("lock")
                action_kind = "secondary"
                guidance_text = self.text("guidance_ready")
            else:
                state_text = self.text("locked", mode=mode)
                action_text = self.text("unlock")
                action_kind = "primary"
                guidance_text = self.text("guidance_reset")

        self.backend_var.set(backend_text)
        self.state_var.set(state_text)
        self.guidance_var.set(guidance_text)
        if self.action_button is not None:
            self.action_button.configure(text=action_text, kind=action_kind)
        reset_button = getattr(self, "reset_button", None)
        if reset_button is not None:
            if self.current_state == "locked":
                reset_button.grid()
            else:
                reset_button.grid_remove()

    def _refresh_agent_cache(self, command: str) -> None:
        try:
            refresh_agent_records(preferred_language=self.language, command=command)
        except Exception:
            pass

    def manage_vault(self) -> None:
        try:
            status = vault_status()
            state = str(status.get("state") or "unknown")
            mode = str(status.get("mode") or "manual_once")
            if state == "uninitialized":
                passphrase = self._prompt_vault_passphrase(confirm=True)
                if passphrase is None:
                    return
                setup_linux_vault(mode="manual_once", passphrase=passphrase, unlock=True)
                messagebox.showinfo(self.text("vault_ready_title"), self.text("vault_ready_body"), parent=self.root)
            elif state == "unlocked":
                lock_linux_vault()
            else:
                passphrase = self._prompt_vault_passphrase(confirm=False)
                if passphrase is None:
                    return
                unlock_linux_vault(passphrase)
        except ProfileError as exc:
            messagebox.showerror(self.text("vault_error_title"), str(exc), parent=self.root)
            return
        self.refresh_status()
        self._refresh_agent_cache("vault.ui.manage")

    def reset_vault(self) -> None:
        if not self._confirm_vault_reset():
            return
        try:
            reset_linux_vault()
        except ProfileError as exc:
            messagebox.showerror(self.text("vault_error_title"), str(exc), parent=self.root)
            return
        self.refresh_status()
        messagebox.showinfo(self.text("reset_success_title"), self.text("reset_success_body"), parent=self.root)
        self._refresh_agent_cache("vault.ui.reset")

    def _perform_requested_action(self) -> None:
        if self.requested_action == "setup" and self.current_state == "uninitialized":
            self.manage_vault()
        elif self.requested_action == "unlock" and self.current_state == "locked":
            self.manage_vault()


def build_cli_parser(language: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=TEXTS[language]["body"],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="help")
    parser.add_argument("--language", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--requested-action", choices=SUPPORTED_VAULT_ACTIONS, default=None, help=argparse.SUPPRESS)
    return parser


def main(
    language: str | None = None,
    requested_action: Optional[str] = None,
    argv: Optional[list[str]] = None,
) -> int:
    parser_language = resolve_language(language)
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    parsed_args = build_cli_parser(parser_language).parse_args(effective_argv)
    resolved_language = resolve_language(language or parsed_args.language)
    effective_requested_action = requested_action or parsed_args.requested_action
    if "-h" not in effective_argv and "--help" not in effective_argv:
        detach_argv = list(effective_argv)
        if effective_requested_action and "--requested-action" not in detach_argv:
            detach_argv = ["--requested-action", effective_requested_action, *detach_argv]
        maybe_detach_gui_entrypoint(
            resolved_language,
            entrypoint_path=Path(__file__),
            argv=detach_argv,
            label="vault-manager",
        )
    maybe_reexec_under_managed_gui_runtime(
        resolved_language,
        entrypoint_path=Path(__file__),
        argv=[
            "--language",
            resolved_language,
            *(["--requested-action", effective_requested_action] if effective_requested_action else []),
        ],
    )
    _load_runtime_dependencies(resolved_language)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(TEXTS[resolved_language]["runtime_unavailable"]) from exc
    VaultManagerApp(root, resolved_language, effective_requested_action)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
