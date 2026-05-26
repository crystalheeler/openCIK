#!/usr/bin/env python3
"""
Inject our DeviceAdminReceiver into p4a's SDL2 bootstrap.

Why this lives in patches/ instead of just adding flags to buildozer.spec:
  - Buildozer's spec exposes hooks for <service>, <activity>,
    <uses-permission>, <meta-data>, etc. — but NOT <receiver>.
  - p4a's `--add-resource` flag (which `android.add_resources`
    translates to) interprets the trailing `:xml` as a destination
    *filename*, not subdirectory, and writes the file at `res/xml`
    overwriting the `xml/` directory.

So we patch p4a's bootstrap directly. The bootstrap files persist
across dist regenerations (buildozer copies FROM bootstrap TO dist
on each build), so our patches survive `buildozer android clean`
and version bumps.

Both patches are idempotent — running again is a no-op.

When to run:
  Before every `buildozer android debug` invocation. Wrapped by
  android/build.sh (which we don't strictly need anymore now that
  the patches are at the bootstrap level — running buildozer
  directly after this script also works).
"""

import os
import shutil
import sys


MARKER = '<!-- OPENCIK_ADMIN_RECEIVER_INJECTED -->'

RECEIVER_XML = (
    MARKER + '\n'
    '        <receiver\n'
    '            android:name="io.crystalheeler.opencik.AdminReceiver"\n'
    '            android:label="@string/app_name"\n'
    '            android:description="@string/app_name"\n'
    '            android:permission="android.permission.BIND_DEVICE_ADMIN"\n'
    '            android:exported="true">\n'
    '            <meta-data\n'
    '                android:name="android.app.device_admin"\n'
    '                android:resource="@xml/device_admin" />\n'
    '            <intent-filter>\n'
    '                <action android:name="android.app.action.DEVICE_ADMIN_ENABLED" />\n'
    '            </intent-filter>\n'
    '        </receiver>\n'
)


def bootstrap_root(repo_root):
    """
    Return p4a's _sdl_common bootstrap dir, or None if it doesn't
    exist yet (means buildozer has never been run; user should run
    buildozer once first to populate .buildozer/).
    """
    candidate = os.path.join(
        repo_root,
        'android', '.buildozer', 'android', 'platform',
        'python-for-android', 'pythonforandroid', 'bootstraps',
        '_sdl_common', 'build',
    )
    return candidate if os.path.isdir(candidate) else None


def dist_root(repo_root):
    """
    Return the per-build dist dir, or None on first build.
    """
    candidate = os.path.join(
        repo_root,
        'android', '.buildozer', 'android', 'platform',
        'build-arm64-v8a_armeabi-v7a', 'dists', 'opencik',
    )
    return candidate if os.path.isdir(candidate) else None


def patch_manifest_template(template_path):
    """Splice our receiver block into the template, idempotently."""
    with open(template_path, encoding='utf-8') as f:
        content = f.read()
    if MARKER in content:
        return False
    if '</application>' not in content:
        sys.exit(
            f'patch: could not find </application> in {template_path}'
        )
    new_content = content.replace(
        '</application>',
        RECEIVER_XML + '    </application>',
        1,
    )
    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    return True


def install_device_admin_resource(repo_root, target_res_dir):
    """
    Copy res/xml/device_admin.xml from our source tree into target_res_dir.

    Handles the case where some earlier --add-resource handling left a
    *file* called `xml` in place of an `xml/` directory: deletes the
    file first, then recreates as a directory.
    """
    src = os.path.join(
        repo_root, 'android', 'res', 'xml', 'device_admin.xml',
    )
    if not os.path.exists(src):
        sys.exit(f'patch: missing source resource {src}')

    xml_dir = os.path.join(target_res_dir, 'xml')

    if os.path.exists(xml_dir) and not os.path.isdir(xml_dir):
        print(f'  removing stale non-dir at {xml_dir}')
        os.remove(xml_dir)

    os.makedirs(xml_dir, exist_ok=True)
    dst = os.path.join(xml_dir, 'device_admin.xml')
    shutil.copyfile(src, dst)
    return dst


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(here, '..', '..'))

    bs = bootstrap_root(repo_root)
    if bs is None:
        print(
            'patch: p4a bootstrap not found yet — this is normal on '
            'a fresh build. Run `buildozer android debug` once to let '
            'it populate .buildozer/, then re-run this script.'
        )
        return 0

    # Bootstrap-level patches — these survive dist regeneration
    bs_template = os.path.join(
        bs, 'templates', 'AndroidManifest.tmpl.xml',
    )
    if os.path.exists(bs_template):
        patched = patch_manifest_template(bs_template)
        print(f'patch: bootstrap manifest template '
              f'{"patched" if patched else "already patched"}: {bs_template}')

    bs_res = os.path.join(bs, 'src', 'main', 'res')
    if os.path.isdir(bs_res):
        installed = install_device_admin_resource(repo_root, bs_res)
        print(f'patch: bootstrap resource installed at {installed}')

    # Dist-level patches — belt-and-suspenders for the existing dist
    # so we don't need to force a regen.
    dist = dist_root(repo_root)
    if dist is not None:
        dist_template = os.path.join(
            dist, 'templates', 'AndroidManifest.tmpl.xml',
        )
        if os.path.exists(dist_template):
            patched = patch_manifest_template(dist_template)
            print(f'patch: dist manifest template '
                  f'{"patched" if patched else "already patched"}: {dist_template}')

        dist_res = os.path.join(dist, 'src', 'main', 'res')
        if os.path.isdir(dist_res):
            installed = install_device_admin_resource(repo_root, dist_res)
            print(f'patch: dist resource installed at {installed}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
