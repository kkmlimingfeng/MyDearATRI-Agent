import json
import http.client
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import web_server
from web_server import _avatar_catalog, _create_avatar, _parse_avatar_upload, _resolve_avatar_asset


class AvatarAssetTests(unittest.TestCase):
    def test_catalog_discovers_live2d_images_and_character_click_audio(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            data_dir = Path(temporary_dir)
            atri = data_dir / "atri"
            (atri / "live2d").mkdir(parents=True)
            (atri / "click").mkdir()
            (atri / "live2d" / "atri.model3.json").write_text(json.dumps({
                "FileReferences": {
                    "Expressions": [{"Name": "expression2", "File": "expression2.exp3.json"}],
                },
            }), encoding="utf-8")
            (atri / "click" / "click.wav").write_bytes(b"audio")

            deepseek = data_dir / "deepseek-0" / "live2d"
            deepseek.mkdir(parents=True)
            (deepseek / "manifest.json").write_text(json.dumps({
                "displayName": "DeepSeek",
                "url": "model.model3.json",
                "expressions": {"开心": {"file": "expressions/happy.exp3.json"}},
            }), encoding="utf-8")
            (deepseek / "model.model3.json").write_text("{}", encoding="utf-8")

            static_pet = data_dir / "static-pet"
            (static_pet / "click").mkdir(parents=True)
            (static_pet / "pet.PNG").write_bytes(b"image")
            (static_pet / "click" / "tap.mp3").write_bytes(b"audio")
            theme = data_dir / "theme"
            theme.mkdir()
            (theme / "background.webp").write_bytes(b"image")

            avatars = _avatar_catalog(data_dir)
            self.assertEqual([avatar["id"] for avatar in avatars], ["atri", "deepseek-0", "static-pet"])
            self.assertEqual(avatars[0]["type"], "live2d")
            self.assertEqual(avatars[0]["expressions"], [{"name": "expression2", "label": "表情 02"}])
            self.assertTrue(avatars[0]["clickAudioUrl"].startswith("/api/avatar-click-audio?character=atri"))
            self.assertEqual(avatars[1]["expressions"], [{"name": "开心", "label": "开心"}])
            self.assertEqual(avatars[2]["type"], "image")
            self.assertEqual(avatars[2]["assetUrl"], "/api/avatar-assets/static-pet/pet.PNG")
            self.assertIn("character=static-pet", avatars[2]["clickAudioUrl"])

    def test_asset_resolution_allows_character_assets_but_blocks_click_and_traversal(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            data_dir = Path(temporary_dir)
            avatar = data_dir / "pet"
            (avatar / "live2d" / "textures").mkdir(parents=True)
            (avatar / "click").mkdir()
            (avatar / "pet.png").write_bytes(b"image")
            (avatar / "live2d" / "model.model3.json").write_text("{}", encoding="utf-8")
            (avatar / "live2d" / "textures" / "texture_00.png").write_bytes(b"texture")
            (avatar / "click" / "sound.wav").write_bytes(b"audio")

            self.assertEqual(_resolve_avatar_asset("pet", "pet.png", data_dir), avatar / "pet.png")
            self.assertEqual(
                _resolve_avatar_asset("pet", "live2d/textures/texture_00.png", data_dir),
                avatar / "live2d" / "textures" / "texture_00.png",
            )
            for unsafe_path in ("click/sound.wav", "live2d/../click/sound.wav", "../pet/pet.png", "pet.png\\.."):
                with self.subTest(path=unsafe_path):
                    self.assertIsNone(_resolve_avatar_asset("pet", unsafe_path, data_dir))
            self.assertIsNone(_resolve_avatar_asset("../pet", "pet.png", data_dir))

    def test_create_avatar_from_png_and_live2d_folder(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            data_dir = Path(temporary_dir)
            _create_avatar("静态桌宠", [("custom.png", b"png-bytes")], data_dir)
            _create_avatar("model-pet", [
                ("live2d/model.model3.json", b"{}"),
                ("live2d/textures/texture_00.png", b"texture"),
            ], data_dir)

            avatars = _avatar_catalog(data_dir)
            self.assertEqual([avatar["characterId"] for avatar in avatars], ["model-pet", "静态桌宠"])
            self.assertEqual((data_dir / "静态桌宠" / "custom.png").read_bytes(), b"png-bytes")
            self.assertEqual((data_dir / "model-pet" / "live2d" / "textures" / "texture_00.png").read_bytes(), b"texture")

    def test_create_avatar_accepts_common_static_image_formats(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            data_dir = Path(temporary_dir)
            for extension in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                name = f"pet-{extension[1:]}"
                content = f"image-{extension}".encode("ascii")
                _create_avatar(name, [(f"pet{extension}", content)], data_dir)

            avatars = _avatar_catalog(data_dir)
            self.assertEqual(
                {avatar["characterId"] for avatar in avatars},
                {"pet-png", "pet-jpg", "pet-jpeg", "pet-gif", "pet-webp"},
            )
            self.assertEqual(
                {avatar["assetUrl"].rsplit(".", 1)[-1] for avatar in avatars},
                {"png", "jpg", "jpeg", "gif", "webp"},
            )

    def test_create_avatar_rejects_existing_names_and_unsafe_upload_paths(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            data_dir = Path(temporary_dir)
            existing = data_dir / "existing"
            existing.mkdir()
            (existing / "keep.png").write_bytes(b"keep")

            for name, files in (
                ("existing", [("new.png", b"new")]),
                ("../escape", [("new.png", b"new")]),
                ("unsupported-image", [("pet.svg", b"svg")]),
                ("unsafe", [("live2d/../keep.png", b"bad")]),
                ("not-model", [("live2d/readme.txt", b"text")]),
            ):
                with self.subTest(name=name, files=files), self.assertRaises(ValueError):
                    _create_avatar(name, files, data_dir)

            self.assertEqual((existing / "keep.png").read_bytes(), b"keep")
            self.assertFalse((data_dir.parent / "escape").exists())

    def test_multipart_avatar_upload_preserves_live2d_relative_paths(self):
        boundary = "atri-upload-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\n宠物一\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"paths\"\r\n\r\nlive2d/model.model3.json\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"model.model3.json\"\r\n"
            "Content-Type: application/json\r\n\r\n{}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"paths\"\r\n\r\nlive2d/textures/tex.png\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"tex.png\"\r\n"
            "Content-Type: image/png\r\n\r\ntexture-data\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        name, files = _parse_avatar_upload(f"multipart/form-data; boundary={boundary}", body)

        self.assertEqual(name, "宠物一")
        self.assertEqual(files, [
            ("live2d/model.model3.json", b"{}"),
            ("live2d/textures/tex.png", b"texture-data"),
        ])

    def test_create_avatar_http_endpoint_saves_and_returns_catalog(self):
        with tempfile.TemporaryDirectory() as temporary_dir, patch.object(web_server, "AVATAR_DATA_DIR", Path(temporary_dir)):
            server = ThreadingHTTPServer(("127.0.0.1", 0), web_server.ApiHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            boundary = "avatar-http-test"
            body = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\nhttp-pet\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"pet.gif\"\r\n"
                "Content-Type: image/gif\r\n\r\ngif-bytes\r\n"
                f"--{boundary}--\r\n"
            ).encode("ascii")
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("POST", "/api/avatars/create", body, {
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                })
                response = connection.getresponse()
                payload = json.loads(response.read())
                connection.close()

                self.assertEqual(response.status, 201)
                self.assertEqual(payload["avatar"]["characterId"], "http-pet")
                self.assertEqual(payload["avatars"][0]["type"], "image")
                self.assertEqual((Path(temporary_dir) / "http-pet" / "pet.gif").read_bytes(), b"gif-bytes")

                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", "/api/avatar-assets/http-pet/pet.gif")
                image_response = connection.getresponse()
                self.assertEqual(image_response.status, 200)
                self.assertEqual(image_response.getheader("Content-Type"), "image/gif")
                self.assertEqual(image_response.read(), b"gif-bytes")
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
