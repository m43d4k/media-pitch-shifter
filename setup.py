from setuptools import setup


setup(
    packages=[],
    app=["pitch_shift_gui.py"],
    options={
        "py2app": {
            "plist": {
                "CFBundleIdentifier": "local.media-pitch-shifter",
                "CFBundleName": "Media Pitch Shifter",
                "CFBundleDisplayName": "Media Pitch Shifter",
            },
        },
    },
)
