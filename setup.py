from setuptools import setup

from py2app.build_app import py2app


class BuildApp(py2app):
    def finalize_options(self):
        # uv manages runtime dependencies. py2app rejects install_requires.
        self.distribution.install_requires = []
        super().finalize_options()


setup(
    packages=[],
    app=["pitch_shift_gui.py"],
    cmdclass={"py2app": BuildApp},
    options={
        "py2app": {
            "iconfile": "assets/AppIcon.icns",
            "plist": {
                "CFBundleIdentifier": "local.media-pitch-shifter",
                "CFBundleName": "Media Pitch Shifter",
                "CFBundleDisplayName": "Media Pitch Shifter",
            },
        },
    },
)
