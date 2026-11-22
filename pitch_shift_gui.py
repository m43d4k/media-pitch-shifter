"""macOS drag-and-drop interface for the shared pitch shifter."""

import logging
import sys
from functools import partial
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QThread, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pitch_shift import download_youtube, inspect_media, parse_semitones, shift, youtube_video_url


APP_NAME = "Media Pitch Shifter"
DROP_HINT = (
    "動画または音声ファイルをドロップ\n"
    "動画  .mp4 .m4v .mov .mkv .webm .avi .ts .mts .m2ts .mpg .mpeg\n"
    "音声  .wav .aif .aiff .flac .m4a .aac .mp3 .ogg .opus .wma"
)


class Job(QThread):
    def __init__(self, operation, on_success, parent):
        super().__init__(parent)
        self.operation = operation
        self.on_success = on_success
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.operation()
        except (OSError, ValueError) as error:
            self.error = str(error)
        except Exception as error:
            logging.exception("処理中に予期しないエラーが発生しました")
            self.error = f"{type(error).__name__}：{error}"


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.source = None
        self.job = None
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.setMinimumWidth(460)

        self.drop_area = QLabel(DROP_HINT)
        self.drop_area.setTextFormat(Qt.TextFormat.PlainText)
        self.drop_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_area.setFrameShape(QFrame.Shape.StyledPanel)
        self.drop_area.setWordWrap(True)
        self.drop_area.setMinimumHeight(80)

        self.youtube_url = QLineEdit()
        self.youtube_url.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.download = QPushButton("yt-dlpで取得")
        self.download.setEnabled(False)
        self.download.clicked.connect(self.download_video)
        self.youtube_url.textChanged.connect(self.update_download_button)
        self.youtube_url.returnPressed.connect(self.download_video)
        youtube_row = QHBoxLayout()
        youtube_row.addWidget(self.youtube_url, stretch=1)
        youtube_row.addWidget(self.download)

        self.download_folder = QLineEdit()
        self.download_folder.setReadOnly(True)
        self.download_folder.setPlaceholderText("フォルダを選択")
        self.choose_folder = QPushButton("選択…")
        self.choose_folder.clicked.connect(self.choose_download_folder)
        download_folder_row = QHBoxLayout()
        download_folder_row.addWidget(self.download_folder, stretch=1)
        download_folder_row.addWidget(self.choose_folder)

        self.semitones = QLineEdit("0")
        self.semitones.setPlaceholderText("例：-2.5")
        self.postfix = QLineEdit("shift")
        self.output_format = QComboBox()
        self.output_format.setPlaceholderText("出力形式を選択")
        self.tracks = QComboBox()
        self.formants = QCheckBox()
        self.formants.setChecked(True)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.form.setHorizontalSpacing(10)
        self.form.addRow("YouTube URL", youtube_row)
        self.form.addRow("ダウンロード先", download_folder_row)
        self.form.addRow("Pitch (st)", self.semitones)
        self.form.addRow("Postfix", self.postfix)
        self.form.addRow("出力形式", self.output_format)
        self.form.addRow("音声トラック", self.tracks)
        self.form.addRow("フォルマントを保持", self.formants)
        self.form.setRowVisible(self.output_format, False)
        self.form.setRowVisible(self.tracks, False)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.convert = QPushButton("変換")
        self.convert.setEnabled(False)
        self.convert.clicked.connect(self.convert_file)
        self.semitones.textChanged.connect(self.update_convert_button)
        self.postfix.textChanged.connect(self.update_convert_button)
        self.output_format.currentIndexChanged.connect(self.update_convert_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.drop_area)
        layout.addLayout(self.form)
        layout.addWidget(self.status)
        layout.addWidget(self.convert, alignment=Qt.AlignmentFlag.AlignRight)

    def drop_path(self, event):
        urls = event.mimeData().urls()
        if self.job is None and len(urls) == 1 and urls[0].isLocalFile():
            return Path(urls[0].toLocalFile())
        return None

    def dragEnterEvent(self, event):
        if self.drop_path(event) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    def dropEvent(self, event):
        path = self.drop_path(event)
        if path is None:
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.clear_media()
        self.drop_area.setText(path.name)
        self.start_job(partial(inspect_media, path), partial(self.load_media, path), "入力ファイルを確認中…")

    def clear_media(self):
        self.source = None
        self.tracks.clear()
        self.form.setRowVisible(self.tracks, False)
        self.output_format.clear()
        self.form.setRowVisible(self.output_format, False)

    def update_download_button(self):
        self.download.setEnabled(self.job is None and bool(self.youtube_url.text().strip()))

    def choose_download_folder(self):
        initial = self.download_folder.text() or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        folder = QFileDialog.getExistingDirectory(self, "YouTube 動画のダウンロード先を選択", initial)
        if folder:
            self.download_folder.setText(folder)
            self.download_folder.setToolTip(folder)
        return folder

    def download_video(self):
        if not self.download.isEnabled():
            return
        try:
            url = youtube_video_url(self.youtube_url.text())
        except ValueError as error:
            self.show_error(str(error))
            return
        folder = self.download_folder.text() or self.choose_download_folder()
        if not folder:
            return

        def fetch_video():
            path = download_youtube(url, Path(folder))
            return path, inspect_media(path)

        self.start_job(fetch_video, self.load_download, "YouTube 動画を取得中…")

    def load_download(self, result):
        path, media = result
        self.clear_media()
        self.load_media(path, media)
        self.status.setText(f"YouTube 動画を取得しました：{path}")

    def load_media(self, path, media):
        for index, track in enumerate(media.audio_tracks):
            tags = track.get("tags", {})
            description = " · ".join(
                field for field in (track.get("codec_name"), tags.get("language"), tags.get("title")) if field
            )
            self.tracks.addItem(f"{index}  {description}".rstrip())
        self.form.setRowVisible(self.tracks, self.tracks.count() > 1)

        needs_format = path.suffix.lower() not in media.output_codecs
        if needs_format:
            self.output_format.addItems(list(media.output_codecs))
            self.output_format.setCurrentIndex(-1)
        self.form.setRowVisible(self.output_format, needs_format)
        self.drop_area.setText(path.name)
        self.status.clear()
        self.source = path

    def output_postfix(self):
        postfix = self.postfix.text()
        if not postfix.strip() or any(character in postfix for character in "/:\0"):
            raise ValueError("ファイル名に使えるポストフィクスを入力してください")
        return postfix

    def output_path(self):
        postfix = self.output_postfix()
        suffix = self.source.suffix
        if self.form.isRowVisible(self.output_format):
            suffix = self.output_format.currentText()
            if not suffix:
                raise ValueError("出力形式を選択してください")
        return self.source.with_name(f"{self.source.stem}_{postfix}{suffix}")

    def update_convert_button(self):
        self.convert.setEnabled(False)
        self.postfix.setToolTip("")
        self.semitones.setToolTip("")
        if self.source is None or self.job is not None:
            return
        try:
            self.output_postfix()
        except ValueError as error:
            self.postfix.setToolTip(str(error))
            return
        if self.form.isRowVisible(self.output_format) and not self.output_format.currentText():
            return
        try:
            parse_semitones(self.semitones.text())
        except ValueError as error:
            self.semitones.setToolTip(str(error))
            return
        self.convert.setEnabled(True)

    def convert_file(self):
        try:
            output = self.output_path()
            semitones = parse_semitones(self.semitones.text())
            try:
                existing = output.lstat()
            except FileNotFoundError:
                existing = None
        except (OSError, ValueError) as error:
            self.show_error(str(error))
            return

        if existing is not None:
            prompt = QMessageBox(self)
            prompt.setIcon(QMessageBox.Icon.Question)
            prompt.setWindowTitle("上書きの確認")
            prompt.setTextFormat(Qt.TextFormat.PlainText)
            prompt.setText(f"「{output.name}」は既に存在します。")
            overwrite = prompt.addButton("上書き", QMessageBox.ButtonRole.AcceptRole)
            cancel = prompt.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
            prompt.setDefaultButton(cancel)
            prompt.exec()
            if prompt.clickedButton() != overwrite:
                return

        operation = partial(
            shift, self.source, output, semitones, self.tracks.currentIndex(),
            self.formants.isChecked(), replace_existing=existing,
        )
        self.start_job(operation, partial(self.saved, output), "変換中…")

    def saved(self, output, _result):
        self.status.setText(f"保存しました：{output.name}")

    def start_job(self, operation, on_success, message):
        self.job = Job(operation, on_success, self)
        self.status.setText(message)
        self.set_controls_enabled(False)
        self.update_convert_button()
        self.job.finished.connect(self.finish_job)
        self.job.start()

    def finish_job(self):
        job, self.job = self.job, None
        job.wait()
        job.deleteLater()
        self.set_controls_enabled(True)
        if job.error is None:
            job.on_success(job.result)
        else:
            if self.source is None:
                self.drop_area.setText(DROP_HINT)
            self.show_error(job.error)
        self.update_convert_button()

    def set_controls_enabled(self, enabled):
        self.choose_folder.setEnabled(enabled)
        for widget in (self.youtube_url, self.semitones, self.postfix, self.output_format, self.tracks, self.formants):
            widget.setEnabled(enabled)
        self.update_download_button()

    def show_error(self, error):
        self.status.setText("処理に失敗しました")
        message, _, detail = error.partition("\n")
        dialog = QMessageBox(QMessageBox.Icon.Critical, "処理エラー", "", parent=self)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(message)
        if detail:
            dialog.setDetailedText(detail)
        dialog.exec()

    def closeEvent(self, event):
        if self.job is not None:
            event.ignore()
        else:
            super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
