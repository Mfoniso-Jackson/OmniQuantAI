#!/usr/bin/env python3
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import weex_vault_manager_app as app  # noqa: E402


class FakeVar:
    def __init__(self, value: object = "") -> None:
        self.value = value

    def get(self) -> object:
        return self.value

    def set(self, value: object) -> None:
        self.value = value


class FakeButton:
    def __init__(self) -> None:
        self.configured: dict[str, object] = {}

    def configure(self, **kwargs: object) -> None:
        self.configured.update(kwargs)


class VaultManagerAppTests(unittest.TestCase):
    def test_main_checks_managed_gui_runtime_before_loading_tk(self) -> None:
        fake_root = types.SimpleNamespace(mainloop=mock.Mock())

        with mock.patch.object(app, "_load_runtime_dependencies"):
            with mock.patch.object(app, "VaultManagerApp"):
                with mock.patch.object(app, "maybe_detach_gui_entrypoint"):
                    with mock.patch.object(app, "maybe_reexec_under_managed_gui_runtime") as bootstrap_mock:
                        with mock.patch.object(
                            app,
                            "tk",
                            types.SimpleNamespace(Tk=mock.Mock(return_value=fake_root), TclError=RuntimeError),
                        ):
                            exit_code = app.main("en", requested_action="setup", argv=[])

        self.assertEqual(exit_code, 0)
        bootstrap_mock.assert_called_once()
        bootstrap_kwargs = bootstrap_mock.call_args.kwargs
        self.assertEqual(bootstrap_kwargs["argv"], ["--language", "en", "--requested-action", "setup"])
        self.assertTrue(str(bootstrap_kwargs["entrypoint_path"]).endswith("weex_vault_manager_app.py"))

    def test_refresh_status_uses_backend_unavailable_copy_on_error(self) -> None:
        vault_app = app.VaultManagerApp.__new__(app.VaultManagerApp)
        vault_app.language = "en"
        vault_app.texts = app.TEXTS["en"]
        vault_app.text = lambda key, **kwargs: app.TEXTS["en"][key].format(**kwargs) if kwargs else app.TEXTS["en"][key]
        vault_app.backend_var = FakeVar()
        vault_app.state_var = FakeVar()
        vault_app.guidance_var = FakeVar()
        vault_app.action_button = None
        vault_app.current_state = "unknown"

        with mock.patch.object(app, "vault_status", side_effect=app.ProfileError("vault broke")):
            vault_app.refresh_status()

        self.assertEqual(vault_app.backend_var.get(), "Application Vault (unavailable)")
        self.assertEqual(vault_app.state_var.get(), "vault broke")
        self.assertEqual(vault_app.guidance_var.get(), app.TEXTS["en"]["guidance_error"])
        self.assertEqual(vault_app.current_state, "error")

    def test_manage_vault_shows_error_when_status_lookup_fails(self) -> None:
        vault_app = app.VaultManagerApp.__new__(app.VaultManagerApp)
        vault_app.language = "en"
        vault_app.texts = app.TEXTS["en"]
        vault_app.text = lambda key, **kwargs: app.TEXTS["en"][key].format(**kwargs) if kwargs else app.TEXTS["en"][key]
        vault_app.root = object()

        fake_messagebox = types.SimpleNamespace(
            showwarning=mock.Mock(),
            showerror=mock.Mock(),
            showinfo=mock.Mock(),
        )

        with mock.patch.object(app, "messagebox", fake_messagebox):
            with mock.patch.object(app, "vault_status", side_effect=app.ProfileError("vault broke")):
                vault_app.manage_vault()

        fake_messagebox.showerror.assert_called_once_with(
            app.TEXTS["en"]["vault_error_title"],
            "vault broke",
            parent=vault_app.root,
        )

    def test_manage_vault_prompts_once_during_unlock(self) -> None:
        vault_app = app.VaultManagerApp.__new__(app.VaultManagerApp)
        vault_app.language = "en"
        vault_app.texts = app.TEXTS["en"]
        vault_app.text = lambda key, **kwargs: app.TEXTS["en"][key].format(**kwargs) if kwargs else app.TEXTS["en"][key]
        vault_app.root = object()
        vault_app.refresh_status = mock.Mock()
        vault_app._refresh_agent_cache = mock.Mock()

        with mock.patch.object(app, "vault_status", return_value={"state": "locked", "mode": "manual_once"}):
            with mock.patch.object(vault_app, "_prompt_vault_passphrase", return_value="vault-passphrase") as prompt_mock:
                with mock.patch.object(app, "unlock_linux_vault") as unlock_mock:
                    vault_app.manage_vault()

        prompt_mock.assert_called_once_with(confirm=False)
        unlock_mock.assert_called_once_with("vault-passphrase")

    def test_refresh_status_shows_reset_button_only_when_locked(self) -> None:
        vault_app = app.VaultManagerApp.__new__(app.VaultManagerApp)
        vault_app.language = "en"
        vault_app.texts = app.TEXTS["en"]
        vault_app.text = lambda key, **kwargs: app.TEXTS["en"][key].format(**kwargs) if kwargs else app.TEXTS["en"][key]
        vault_app.backend_var = FakeVar()
        vault_app.state_var = FakeVar()
        vault_app.guidance_var = FakeVar()
        vault_app.action_button = FakeButton()
        vault_app.reset_button = types.SimpleNamespace(grid=mock.Mock(), grid_remove=mock.Mock())
        vault_app.current_state = "unknown"

        with mock.patch.object(app, "vault_status", return_value={"state": "locked", "mode": "manual_once"}):
            with mock.patch.object(app, "secure_store_backend_name", return_value="Application Vault (manual_once)"):
                vault_app.refresh_status()

        vault_app.reset_button.grid.assert_called_once()
        vault_app.reset_button.grid_remove.assert_not_called()

    def test_reset_vault_executes_destructive_reset_flow(self) -> None:
        vault_app = app.VaultManagerApp.__new__(app.VaultManagerApp)
        vault_app.language = "en"
        vault_app.texts = app.TEXTS["en"]
        vault_app.text = lambda key, **kwargs: app.TEXTS["en"][key].format(**kwargs) if kwargs else app.TEXTS["en"][key]
        vault_app.root = object()
        vault_app.refresh_status = mock.Mock()
        vault_app._refresh_agent_cache = mock.Mock()
        vault_app._confirm_vault_reset = mock.Mock(return_value=True)

        fake_messagebox = types.SimpleNamespace(showinfo=mock.Mock(), showerror=mock.Mock())

        with mock.patch.object(app, "messagebox", fake_messagebox):
            with mock.patch.object(app, "reset_linux_vault", return_value={"state": "uninitialized"}) as reset_mock:
                vault_app.reset_vault()

        reset_mock.assert_called_once_with()
        vault_app.refresh_status.assert_called_once()
        vault_app._refresh_agent_cache.assert_called_once()

    def test_requested_action_status_and_lock_do_not_auto_manage(self) -> None:
        vault_app = app.VaultManagerApp.__new__(app.VaultManagerApp)
        vault_app.manage_vault = mock.Mock()

        vault_app.requested_action = "status"
        vault_app.current_state = "locked"
        vault_app._perform_requested_action()

        vault_app.requested_action = "lock"
        vault_app.current_state = "unlocked"
        vault_app._perform_requested_action()

        vault_app.manage_vault.assert_not_called()

    def test_refresh_status_updates_button_text_and_kind(self) -> None:
        vault_app = app.VaultManagerApp.__new__(app.VaultManagerApp)
        vault_app.language = "en"
        vault_app.texts = app.TEXTS["en"]
        vault_app.text = lambda key, **kwargs: app.TEXTS["en"][key].format(**kwargs) if kwargs else app.TEXTS["en"][key]
        vault_app.backend_var = FakeVar()
        vault_app.state_var = FakeVar()
        vault_app.guidance_var = FakeVar()
        vault_app.action_button = FakeButton()
        vault_app.current_state = "unknown"

        with mock.patch.object(app, "vault_status", return_value={"state": "unlocked", "mode": "manual_once"}):
            with mock.patch.object(app, "secure_store_backend_name", return_value="Application Vault (manual_once)"):
                vault_app.refresh_status()

        self.assertEqual(vault_app.action_button.configured["text"], app.TEXTS["en"]["lock"])
        self.assertEqual(vault_app.action_button.configured["kind"], "secondary")


if __name__ == "__main__":
    unittest.main()
