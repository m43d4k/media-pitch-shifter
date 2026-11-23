"""macOS drag-and-drop interface for the shared pitch shifter."""

import logging
import sys
from functools import partial
from html import escape
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths, QThread, Qt, Signal, Slot
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStylePainter,
    QTabWidget,
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


class ElidedLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setTextFormat(Qt.TextFormat.PlainText)
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)

    def sizeHint(self):
        return QSize(0, self.fontMetrics().height())

    def setText(self, text):
        super().setText(" ".join(text.splitlines()))
        self.setToolTip(f'<qt style="white-space: pre-wrap">{escape(text)}</qt>' if text else "")

    def paintEvent(self, event):
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, rect.width())
        painter = QStylePainter(self)
        painter.drawItemText(
            rect, self.alignment().value, self.palette(), self.isEnabled(), text, self.foregroundRole(),
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
    job_progress = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.source = None
        self.source_from_youtube = False
        self.job = None
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.setMinimumWidth(460)

        drop_area = QLabel(DROP_HINT)
        drop_area.setTextFormat(Qt.TextFormat.PlainText)
        drop_area.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        drop_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_area.setWordWrap(True)
        drop_area.setMinimumHeight(80)
        self.drop_tab = QWidget()
        drop_layout = QVBoxLayout(self.drop_tab)
        drop_layout.addWidget(drop_area)

        self.youtube_url = QLineEdit()
        self.youtube_url.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.download = QPushButton("ダウンロード")
        self.download.setEnabled(False)
        self.download.clicked.connect(self.download_video)
        self.youtube_url.textChanged.connect(self.update_download_button)
        self.youtube_url.returnPressed.connect(self.download_video)

        self.download_folder = QLineEdit()
        self.download_folder.setReadOnly(True)
        self.download_folder.setPlaceholderText("フォルダを選択")
        self.choose_folder = QPushButton("選択…")
        self.choose_folder.clicked.connect(self.choose_download_folder)
        download_folder_row = QHBoxLayout()
        download_folder_row.addWidget(self.download_folder, stretch=1)
        download_folder_row.addWidget(self.choose_folder)

        download_button_row = QHBoxLayout()
        download_button_row.addStretch()
        download_button_row.addWidget(self.download)
        download_button_row.addStretch()

        youtube_tab = QWidget()
        youtube_form = QFormLayout(youtube_tab)
        youtube_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        youtube_form.setHorizontalSpacing(10)
        youtube_form.setVerticalSpacing(5)
        youtube_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        youtube_form.addRow("YouTube URL", self.youtube_url)
        youtube_form.addRow("ダウンロード先", download_folder_row)
        youtube_form.addRow(download_button_row)

        for page_layout, top_margin in ((drop_layout, 5), (youtube_form, 12)):
            margins = page_layout.contentsMargins()
            page_layout.setContentsMargins(margins.left(), top_margin, margins.right(), 5)

        self.input_tabs = QTabWidget()
        self.input_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.input_tabs.addTab(self.drop_tab, "ファイル")
        self.input_tabs.addTab(youtube_tab, "YouTube")

        self.semitones = QLineEdit("0")
        self.semitones.setPlaceholderText("例：-2.5")
        self.postfix = QLineEdit("shift")
        self.output_format = QComboBox()
        self.output_format.setPlaceholderText("出力形式を選択")
        self.tracks = QComboBox()
        self.formants = QCheckBox()
        self.formants.setChecked(True)

        self.pitch_settings = QWidget()
        self.form = QFormLayout(self.pitch_settings)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.form.setHorizontalSpacing(48)
        self.form.addRow("Pitch (st)", self.semitones)
        self.form.addRow("フォルマントを保持", self.formants)
        self.form.addRow("出力形式", self.output_format)
        self.form.addRow("音声トラック", self.tracks)
        self.form.addRow("Postfix", self.postfix)
        self.form.setRowVisible(self.output_format, False)
        self.form.setRowVisible(self.tracks, False)

        self.source_label = ElidedLabel()
        self.source_label.hide()
        self.status = ElidedLabel()
        self.job_progress.connect(self.show_job_progress)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("処理の進捗")
        self.progress.setTextVisible(False)
        progress_policy = self.progress.sizePolicy()
        progress_policy.setRetainSizeWhenHidden(True)
        self.progress.setSizePolicy(progress_policy)
        self.progress.hide()
        self.convert = QPushButton("変換")
        self.convert.setEnabled(False)
        self.convert.clicked.connect(self.convert_file)
        self.semitones.textChanged.connect(self.update_convert_button)
        self.postfix.textChanged.connect(self.update_convert_button)
        self.output_format.currentIndexChanged.connect(self.update_convert_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.input_tabs)
        layout.addSpacing(14)
        layout.addWidget(self.source_label)
        layout.addWidget(self.pitch_settings, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addWidget(self.convert, alignment=Qt.AlignmentFlag.AlignRight)
        self.input_tabs.currentChanged.connect(self.update_controls)

    def drop_path(self, event):
        if self.job is not None or self.input_tabs.currentWidget() is not self.drop_tab:
            return None
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
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
        self.start_job(partial(inspect_media, path), partial(self.load_media, path), "入力ファイルを確認中…")

    def clear_media(self):
        self.source = None
        self.source_from_youtube = False
        self.source_label.setText("")
        self.source_label.hide()
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
            path = download_youtube(url, Path(folder), on_progress=self.job_progress.emit)
            self.job_progress.emit("取得した動画を確認中", None)
            return path, inspect_media(path)

        self.start_job(fetch_video, self.load_download, "ダウンロードを準備中…", show_progress=True)

    def load_download(self, result):
        path, media = result
        self.clear_media()
        self.load_media(path, media, from_youtube=True)
        self.finish_progress(f"ダウンロード完了：{path}")

    def load_media(self, path, media, *, from_youtube=False):
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
        self.source_label.setText(f"入力ファイル：{path.name}")
        self.source_label.show()
        self.status.setText("")
        self.source = path
        self.source_from_youtube = from_youtube

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
        if self.source is None or not self.pitch_settings.isEnabled():
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
            self.formants.isChecked(), replace_existing=existing, on_progress=self.job_progress.emit,
        )
        self.start_job(operation, partial(self.saved, output), "変換を準備中…", show_progress=True)

    @Slot(str, object)
    def show_job_progress(self, stage, percent):
        if percent is None:
            self.progress.setRange(0, 0)
            self.status.setText(f"{stage}…")
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            self.status.setText(f"{stage} {percent}%")

    def saved(self, output, _result):
        self.finish_progress(f"変換完了：{output.name} を保存しました")

    def finish_progress(self, message):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.status.setText(message)

    def start_job(self, operation, on_success, message, *, show_progress=False):
        self.job = Job(operation, on_success, self)
        self.status.setText(message)
        if show_progress:
            self.progress.setRange(0, 0)
        self.progress.setVisible(show_progress)
        self.update_controls()
        self.job.finished.connect(self.finish_job)
        self.job.start()

    def finish_job(self):
        job, self.job = self.job, None
        job.wait()
        job.deleteLater()
        if job.error is None:
            job.on_success(job.result)
        self.update_controls()
        if job.error is not None:
            self.show_error(job.error)

    def update_controls(self):
        idle = self.job is None
        self.choose_folder.setEnabled(idle)
        self.youtube_url.setEnabled(idle)
        self.pitch_settings.setEnabled(
            idle and (self.input_tabs.currentWidget() is self.drop_tab or self.source_from_youtube)
        )
        self.update_download_button()
        self.update_convert_button()

    def show_error(self, error):
        self.progress.hide()
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
