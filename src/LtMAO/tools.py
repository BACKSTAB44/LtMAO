import subprocess, math, os
from LtMAO import lepath, ritobin_text
from PIL import Image

def block_and_stream_process_output(process, log_message_header=''):
    for line in process.stdout:
        msg = line.decode().strip().replace('\\', '/')
        if msg != '':
            print(log_message_header + msg)
    process.wait()

def block_and_stream_nothing(process):
    process.wait()


class CSLOL:
    local_file = './res/tools/mod-tools.exe'
    diag_file = './res/tools/cslol-diag.exe'

    @staticmethod
    def import_fantome(src, dst, game=None, noTFT=True):
        local_file = lepath.abs(CSLOL.local_file)
        cmds = [local_file, 'import', src, dst]
        if game:
            cmds.append('--game:' + game)
        if noTFT:
            cmds.append('--noTFT')
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return p

    @staticmethod
    def export_fantome(src, dst, game=None, noTFT=True):
        local_file = lepath.abs(CSLOL.local_file)
        cmds = [local_file, 'export', src, dst]
        if game:
            cmds.append('--game:' + game)
        if noTFT:
            cmds.append('--noTFT')
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return p

    @staticmethod
    def make_overlay(src, overlay, game=None, mods=None, noTFT=True, ignore_conflict=True):
        local_file = lepath.abs(CSLOL.local_file)
        cmds = [local_file, 'mkoverlay', src, overlay]
        if game:
            cmds.append('--game:' + game)
        if mods:
            cmds.append('--mods:' + '/'.join(mods))
        if noTFT:
            cmds.append('--noTFT')
        if ignore_conflict:
            cmds.append('--ignoreConflict')
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return p

    @staticmethod
    def run_overlay(overlay, config, game=None):
        local_file = lepath.abs(CSLOL.local_file)
        cmds = [local_file, 'runoverlay', overlay, config]
        if game:
            cmds.append(game)
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        return p
    
    
    @staticmethod
    def diagnose():
        diag_file = lepath.abs(CSLOL.diag_file)
        cmds = [diag_file]
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        block_and_stream_process_output(p, 'cslol-diag: ')
        return p


class ImageMagick:
    local_file = './res/tools/magick.exe'

    @staticmethod
    def to_png(src, png):
        cmds = [
            lepath.abs(ImageMagick.local_file),
            src,
            png
        ]
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        block_and_stream_process_output(p, 'ImageMagick: ')
        return p

    @staticmethod
    def to_dds(src, dds, format='dxt5', mipmap=False):
        if format not in ('dxt1', 'dxt5'):
            format = 'dxt5'
        if mipmap:
            with Image.open(src) as img:
                mipmap_count = math.floor(math.log2(max(img.width, img.height))) + 1
        cmds = [
            lepath.abs(ImageMagick.local_file),
            src,
            '-define',
            f'dds:compression={format}',
            '-define',
            f'dds:mipmaps={mipmap_count if mipmap else 0}',
            '-alpha',
            'set',
            dds
        ]
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        block_and_stream_process_output(p, 'ImageMagick: ')
        return p

    @staticmethod
    def resize_dds(src, dst, width, height):
        cmds = [
            lepath.abs(ImageMagick.local_file),
            src,
            '-resize',
            f'{width}x{height}',
            dst
        ]
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        block_and_stream_process_output(p, 'ImageMagick: ')
        return p


class VGMStream:
    local_file = './res/tools/vgmstream/vgmstream-cli.exe'

    @staticmethod
    def to_wav(src, dst=None):
        if dst == None:
            dst = '.'.join(src.split('.')[:-1] + ['wav']) 
        cmds = [
            lepath.abs(VGMStream.local_file),
            '-o',
            dst,
            src,
        ]
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        block_and_stream_nothing(p)
        return p
    

class WWiseConsole:
    local_file = './res/wiwawe/WwiseApp/Authoring/x64/Release/bin/WwiseConsole.exe'
    wproj_file = './res/wiwawe/WwiseLeagueProjects/WWiseLeagueProjects.wproj'

    @staticmethod
    def to_wem(wsources_file, output_dir):
        cmds = [
            WWiseConsole.local_file,
            'convert-external-source',
            lepath.abs(WWiseConsole.wproj_file),
            '--source-file',
            lepath.abs(wsources_file),
            '--output',
            lepath.abs(output_dir)
        ]
        p = subprocess.Popen(
            cmds, creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        block_and_stream_process_output(p, 'WwiseConsole: ')
        return p
    
class RITOBIN:
    # LeagueToolkit ritobin-tools v0.2.3 replaces the older ritobin_cli.exe.
    # v0.2.3 supports 8-byte BIN Hash values and the legacy .py text extension.
    local_file = './res/tools/ritobin-tools.exe'

    @staticmethod
    def _is_text_input(input_file, output_file):
        lower = input_file.lower()
        if lower.endswith(('.py', '.rito', '.ritobin')):
            return True
        try:
            with open(input_file, 'rb') as stream:
                magic = stream.read(4)
            if magic in (b'PROP', b'PTCH'):
                return False
        except OSError:
            pass
        # For a not-yet-created path (useful for command planning/tests), infer
        # direction from the requested output extension.
        return not output_file.lower().endswith(('.py', '.rito', '.ritobin'))

    @staticmethod
    def build_commands(file_pairs, dir_hashes=None):
        """Build ritobin-tools commands while preserving every requested output path.

        Conventional pairs are batched into one CLI call. Pairs with custom
        output names use an explicit --output argument and their own process.
        """
        import os

        if len(file_pairs) % 2:
            raise ValueError('RITOBIN.run expects input/output file pairs.')

        executable = lepath.abs(RITOBIN.local_file)
        global_args = ['--hashtable', lepath.abs(dir_hashes)] if dir_hashes else []
        batches = {}
        custom = []
        text_extensions = ('.py', '.rito', '.ritobin')

        for index in range(0, len(file_pairs), 2):
            input_file = file_pairs[index]
            output_file = file_pairs[index + 1]
            output_lower = output_file.lower()
            is_text_input = RITOBIN._is_text_input(input_file, output_file)

            if is_text_input:
                if not input_file.lower().endswith(text_extensions):
                    custom.append((input_file, output_file, 'to_bin', None))
                    continue
                source_extension = next(
                    ext for ext in text_extensions if input_file.lower().endswith(ext)
                )
                default_output = input_file[:-len(source_extension)] + '.bin'
                if (output_lower.endswith('.bin') and
                        os.path.normcase(os.path.abspath(default_output)) ==
                        os.path.normcase(os.path.abspath(output_file))):
                    batches.setdefault(('to_bin', None), []).append(input_file)
                else:
                    custom.append((input_file, output_file, 'to_bin', None))
            else:
                output_extension = next(
                    (ext[1:] for ext in text_extensions if output_lower.endswith(ext)),
                    'py',
                )
                if input_file.lower().endswith('.bin'):
                    default_output = input_file[:-4] + '.' + output_extension
                else:
                    default_output = None
                if (default_output is not None and
                        os.path.normcase(os.path.abspath(default_output)) ==
                        os.path.normcase(os.path.abspath(output_file))):
                    batches.setdefault(('to_text', output_extension), []).append(input_file)
                else:
                    custom.append((input_file, output_file, 'to_text', output_extension))

        commands = []
        for (direction, extension), inputs in batches.items():
            command = [executable, *global_args, 'convert', *inputs]
            if direction == 'to_bin':
                command.extend(('--to', 'bin'))
            else:
                command.extend(('--ext', extension))
            commands.append(command)

        for input_file, output_file, direction, extension in custom:
            command = [executable, *global_args, 'convert', input_file]
            if direction == 'to_bin':
                command.extend(('--to', 'bin'))
            else:
                command.extend(('--ext', extension))
            command.extend(('--output', output_file))
            commands.append(command)

        return commands

    @staticmethod
    def _is_hash_metadata_error(output_lines):
        """Return True only for errors that plausibly need fresh property-hasher metadata."""
        import re

        message = "\n".join(output_lines).lower()
        patterns = (
            r"type mismatch.{0,160}hash\s*\[\s*u(?:32|64)\s*\].{0,100}(?:string|text)",
            r"(?:expected|expecting)\s+hash\s*\[\s*u(?:32|64)\s*\].{0,100}(?:string|text)",
            r"hash\s*\[\s*u(?:32|64)\s*\].{0,120}(?:string|text)",
            r"(?:hash|hasher|hash algorithm).{0,120}(?:algorithm|metadata).{0,100}(?:missing|required|unknown|unsupported|mismatch)",
        )
        return any(re.search(pattern, message, re.IGNORECASE | re.DOTALL) for pattern in patterns)

    @staticmethod
    def _run_captured_command(command):
        """Run one command and hold its output until we know whether retry is needed."""
        try:
            process = subprocess.Popen(
                command,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            return None, [], exc

        output_lines = []
        if process.stdout is not None:
            for raw_line in process.stdout:
                if isinstance(raw_line, bytes):
                    line = raw_line.decode('utf-8', errors='replace').rstrip()
                else:
                    line = str(raw_line).rstrip()
                if line:
                    output_lines.append(line)
        return process.wait(), output_lines, None

    @staticmethod
    def _print_captured_output(output_lines):
        for line in output_lines:
            print(f'ritobin: {line}')

    @staticmethod
    def run(file_pairs, dir_hashes=None):
        """Use LtMAO's original typed Writer for BIN-to-text; use v0.2.3 for text-to-BIN.

        The original Writer formats each BIN value type separately. In particular,
        LIST values are vertical while VEC2/VEC3/VEC4/RGBA values remain inline.
        """
        if not file_pairs:
            return
        if len(file_pairs) % 2:
            raise ValueError('RITOBIN.run expects input/output file pairs.')

        bin_to_text_pairs = []
        text_to_bin_pairs = []
        text_extensions = ('.py', '.rito', '.ritobin')

        for index in range(0, len(file_pairs), 2):
            input_file = file_pairs[index]
            output_file = file_pairs[index + 1]
            is_binary_input = not RITOBIN._is_text_input(input_file, output_file)
            if (is_binary_input
                    and output_file.lower().endswith(text_extensions)):
                bin_to_text_pairs.extend((input_file, output_file))
            else:
                text_to_bin_pairs.extend((input_file, output_file))

        failures = []

        # Keep BIN-to-text on LtMAO's own Python implementation. This is the
        # formatting path used before v3, now backed by the v2 64-bit Hash reader.
        if bin_to_text_pairs:
            from LtMAO import hash_helper, ritobin
            hash_tables = None
            if dir_hashes:
                # The old ritobin_cli.exe loaded all six custom CDragon tables
                # from this directory. Load the same tables for BIN.un_hash().
                hash_helper.CustomHashes.read_all_hashes()
                hash_tables = hash_helper.Storage.hashtables

            for index in range(0, len(bin_to_text_pairs), 2):
                input_file = bin_to_text_pairs[index]
                output_file = bin_to_text_pairs[index + 1]
                print(f'ritobin: Start: {input_file} -> {output_file}')
                try:
                    output_dir = os.path.dirname(os.path.abspath(output_file))
                    if output_dir:
                        os.makedirs(output_dir, exist_ok=True)
                    ritobin.bin_to_text(input_file, output_file, hash_tables)
                    print(f'ritobin: Finish: {input_file} -> {output_file}')
                except Exception as exc:
                    print(f'ritobin: Error: {input_file}: {exc}')
                    failures.append((input_file, output_file, exc))

        # Prepare temporary text copies for metadata-defined scalar Hash strings.
        # The original .py files are never modified. If ritobin-tools reports a
        # likely Hash/string type mismatch, silently refresh metadata outside the
        # 12-hour cooldown and retry the affected command once.
        if text_to_bin_pairs:
            prepared_pairs = []
            temporary_inputs = []
            prepared_to_original = {}
            metadata_retry_attempted = False
            try:
                for index in range(0, len(text_to_bin_pairs), 2):
                    input_file = text_to_bin_pairs[index]
                    output_file = text_to_bin_pairs[index + 1]
                    try:
                        prepared_input, temporary_path, replacements = (
                            ritobin_text.make_temporary_conversion_input(input_file)
                        )
                        if temporary_path:
                            temporary_inputs.append(temporary_path)
                            print(
                                'ritobin: Info: Applied metadata-defined hash annotation to '
                                f'{replacements} property-specific '
                                f'string field(s) in temporary input: {input_file}'
                            )
                        prepared_pairs.extend((prepared_input, output_file))
                        prepared_to_original[prepared_input] = (input_file, output_file)
                    except Exception as exc:
                        print(f'ritobin: Error: Could not prepare {input_file}: {exc}')
                        failures.append((input_file, output_file, exc))

                commands = RITOBIN.build_commands(prepared_pairs, dir_hashes)
                for command in commands:
                    print(f'ritobin: Start: {command[-1] if command else "conversion"}')
                    return_code, output_lines, launch_error = RITOBIN._run_captured_command(command)

                    if launch_error is not None:
                        print(f'ritobin: Error: Could not start converter: {launch_error}')
                        failures.append((command, None, launch_error))
                        continue

                    if return_code == 0:
                        RITOBIN._print_captured_output(output_lines)
                        continue

                    # Only hash/string parser errors can invalidate a metadata
                    # assumption. Syntax errors and unrelated failures keep the
                    # normal, immediate error path without a metadata request.
                    if (not metadata_retry_attempted
                            and RITOBIN._is_hash_metadata_error(output_lines)):
                        metadata_retry_attempted = True
                        refreshed, _refresh_source = ritobin_text.refresh_metadata_for_retry()
                        if refreshed:
                            affected_pairs = []
                            for prepared_input, original_pair in prepared_to_original.items():
                                if prepared_input in command:
                                    affected_pairs.extend(original_pair)

                            retry_pairs = []
                            try:
                                for retry_index in range(0, len(affected_pairs), 2):
                                    original_input = affected_pairs[retry_index]
                                    original_output = affected_pairs[retry_index + 1]
                                    retry_input, retry_temporary, _ = (
                                        ritobin_text.make_temporary_conversion_input(original_input)
                                    )
                                    if retry_temporary:
                                        temporary_inputs.append(retry_temporary)
                                    retry_pairs.extend((retry_input, original_output))
                                retry_commands = RITOBIN.build_commands(retry_pairs, dir_hashes)
                            except Exception as exc:
                                # The first diagnostic is more useful than a
                                # hidden retry-preparation failure; preserve it.
                                RITOBIN._print_captured_output(output_lines)
                                print(f'ritobin: Error: Could not prepare metadata-refresh retry: {exc}')
                                failures.append((command, return_code, exc))
                                continue

                            if retry_commands:
                                retry_succeeded = True
                                for retry_command in retry_commands:
                                    print(f'ritobin: Start: {retry_command[-1] if retry_command else "conversion"}')
                                    retry_code, retry_output, retry_launch_error = (
                                        RITOBIN._run_captured_command(retry_command)
                                    )
                                    if retry_launch_error is not None:
                                        print(f'ritobin: Error: Could not start converter: {retry_launch_error}')
                                        failures.append((retry_command, None, retry_launch_error))
                                        retry_succeeded = False
                                    elif retry_code != 0:
                                        RITOBIN._print_captured_output(retry_output)
                                        print(f'ritobin: Error: converter exited with code {retry_code}.')
                                        failures.append((retry_command, retry_code, None))
                                        retry_succeeded = False
                                    else:
                                        RITOBIN._print_captured_output(retry_output)
                                if retry_succeeded:
                                    # The original hash-related failure was
                                    # intentionally suppressed; the retry worked.
                                    continue
                                continue

                    # Refresh was unavailable, the error was unrelated, or this
                    # run already used its one retry. Show normal diagnostics.
                    RITOBIN._print_captured_output(output_lines)
                    print(f'ritobin: Error: converter exited with code {return_code}.')
                    failures.append((command, return_code, None))
            finally:
                for temporary_path in temporary_inputs:
                    try:
                        os.remove(temporary_path)
                    except OSError as exc:
                        print(
                            'ritobin: Warning: Could not remove temporary input '
                            f'{temporary_path}: {exc}'
                        )

        if failures:
            raise RuntimeError(
                f'Ritobin conversion failed for {len(failures)} file(s)/command(s). '
                'See the ritobin messages above for details.'
            )
