from qtpy import QtWidgets, QtCore, QtGui

import ayon_api

from ayon_core import style
from ayon_core.resources import get_resource
from ayon_core.tools.utils import PressHoverButton

from ayon_kitsu.credentials import (
    clear_credentials,
    load_credentials,
    save_credentials,
    set_credentials_envs,
    validate_credentials,
)

from .version import __version__


class KitsuPasswordDialog(QtWidgets.QDialog):
    """Kitsu login dialog."""

    finished = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super(KitsuPasswordDialog, self).__init__(parent)

        self.setWindowTitle("Kitsu Credentials")
        self.resize(300, 120)

        addon_settings = ayon_api.get_addon_settings("kitsu", __version__)
        server_url = addon_settings["server"]

        user_login, user_pwd = load_credentials()
        remembered = bool(user_login or user_pwd)

        # Server label
        server_message = server_url
        if not server_url:
            server_message = "Server url is not set in Settings..."

        inputs_widget = QtWidgets.QWidget(self)

        server_label = QtWidgets.QLabel("Server:", inputs_widget)
        server_url_label = QtWidgets.QLabel(server_message, inputs_widget)

        # Login input
        login_label = QtWidgets.QLabel("Login:", inputs_widget)

        login_input = QtWidgets.QLineEdit(
            inputs_widget,
            text=user_login if remembered else None,
        )
        login_input.setPlaceholderText("Your Kitsu account login...")

        # Password input
        password_label = QtWidgets.QLabel("Password:", inputs_widget)

        password_wrap_widget = QtWidgets.QWidget(inputs_widget)
        password_input = QtWidgets.QLineEdit(
            password_wrap_widget,
            text=user_pwd if remembered else None,
        )
        password_input.setPlaceholderText("Your password...")
        password_input.setEchoMode(QtWidgets.QLineEdit.Password)

        show_password_icon_path = get_resource("icons", "eye.png")
        show_password_icon = QtGui.QIcon(show_password_icon_path)
        show_password_btn = PressHoverButton(password_wrap_widget)
        show_password_btn.setObjectName("PasswordBtn")
        show_password_btn.setIcon(show_password_icon)
        show_password_btn.setFocusPolicy(QtCore.Qt.ClickFocus)

        password_wrap_layout = QtWidgets.QHBoxLayout(password_wrap_widget)
        password_wrap_layout.setContentsMargins(0, 0, 0, 0)
        password_wrap_layout.addWidget(password_input, 1)
        password_wrap_layout.addWidget(show_password_btn, 0)

        server_url_spacer = QtWidgets.QSpacerItem(5, 5)

        inputs_layout = QtWidgets.QGridLayout(inputs_widget)
        inputs_layout.setContentsMargins(0, 0, 0, 0)
        inputs_layout.addWidget(server_label, 0, 0, QtCore.Qt.AlignRight)
        inputs_layout.addWidget(server_url_label, 0, 1)
        inputs_layout.addItem(server_url_spacer, 1, 0, 1, 2)
        inputs_layout.addWidget(login_label, 2, 0, QtCore.Qt.AlignRight)
        inputs_layout.addWidget(login_input, 2, 1)
        inputs_layout.addWidget(password_label, 3, 0, QtCore.Qt.AlignRight)
        inputs_layout.addWidget(password_wrap_widget, 3, 1)
        inputs_layout.setColumnStretch(0, 0)
        inputs_layout.setColumnStretch(1, 1)

        # Message label
        message_label = QtWidgets.QLabel("", self)

        # Buttons
        buttons_widget = QtWidgets.QWidget(self)

        remember_checkbox = QtWidgets.QCheckBox("Remember", buttons_widget)
        remember_checkbox.setObjectName("RememberCheckbox")
        remember_checkbox.setChecked(remembered)

        ok_btn = QtWidgets.QPushButton("Ok", buttons_widget)
        cancel_btn = QtWidgets.QPushButton("Cancel", buttons_widget)

        buttons_layout = QtWidgets.QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addWidget(remember_checkbox)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(ok_btn)
        buttons_layout.addWidget(cancel_btn)

        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.addSpacing(5)
        layout.addWidget(inputs_widget, 0)
        layout.addWidget(message_label, 0)
        layout.addStretch(1)
        layout.addWidget(buttons_widget, 0)

        ok_btn.clicked.connect(self._on_ok_click)
        cancel_btn.clicked.connect(self._on_cancel_click)
        show_password_btn.change_state.connect(self._on_show_password)

        self._login_input = login_input
        self._password_input = password_input
        self._remember_checkbox = remember_checkbox
        self._message_label = message_label

        self._final_result = None
        self._connectable = bool(server_url)

        self.setStyleSheet(style.load_stylesheet())

    def result(self):
        return self._final_result

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._on_ok_click()
            return event.accept()
        super(KitsuPasswordDialog, self).keyPressEvent(event)

    def closeEvent(self, event):
        super(KitsuPasswordDialog, self).closeEvent(event)
        self.finished.emit(self.result())

    def _on_ok_click(self):
        # Check if is connectable
        if not self._connectable:
            self._message_label.setText("Please set server url in Studio Settings!")
            return

        # Collect values
        login_value = self._login_input.text()
        pwd_value = self._password_input.text()
        remember = self._remember_checkbox.isChecked()

        # Authenticate
        if validate_credentials(login_value, pwd_value):
            set_credentials_envs(login_value, pwd_value)
        else:
            self._message_label.setText("Authentication failed...")
            return

        # Remember password cases
        if remember:
            save_credentials(login_value, pwd_value)
        else:
            # Clear local settings
            clear_credentials()

            # Clear input fields
            self._login_input.clear()
            self._password_input.clear()

        self._final_result = True
        self.close()

    def _on_show_password(self, show_password):
        if show_password:
            echo_mode = QtWidgets.QLineEdit.Normal
        else:
            echo_mode = QtWidgets.QLineEdit.Password
        self._password_input.setEchoMode(echo_mode)

    def _on_cancel_click(self):
        self.close()
