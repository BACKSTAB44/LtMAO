from LtMAO import lepath, pyRitoFile


class HashTypeSpec:
    def __init__(self, width=4, algorithm='fnv1a'):
        self.width = width
        self.algorithm = algorithm


def _split_type_arguments(text):
    parts, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == '[':
            depth += 1
        elif char == ']':
            depth -= 1
        elif char == ',' and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts



def f32_str(num):
    """Return the shortest round-trip-safe f32 as ordinary decimal notation.

    Find the shortest significant-digit representation that converts back to
    the same IEEE-754 binary32 value. Then expand any exponent with Decimal so
    the emitted Ritobin text uses ordinary decimal notation (for example,
    1.2e+02 becomes 120). This keeps the original Writer's compact formatting
    without rounding values to four decimal places or emitting scientific
    notation that the older LtMAO parser may not accept consistently.
    """
    import math
    import struct
    from decimal import Decimal

    value = float(num)
    if math.isnan(value):
        return 'nan'
    if math.isinf(value):
        return '-inf' if value < 0 else 'inf'

    target = struct.pack('<f', value)
    for precision in range(1, 10):
        candidate = format(value, f'.{precision}g')
        try:
            if struct.pack('<f', float(candidate)) == target:
                decimal_text = format(Decimal(candidate), 'f')
                if '.' in decimal_text:
                    decimal_text = decimal_text.rstrip('0').rstrip('.')
                return decimal_text
        except (OverflowError, ValueError):
            continue

    # Nine significant decimal digits are sufficient to round-trip any f32.
    decimal_text = format(Decimal(format(value, '.9g')), 'f')
    if '.' in decimal_text:
        decimal_text = decimal_text.rstrip('0').rstrip('.')
    return decimal_text

def make_escapes(text):
    escape_chars = {
        '\n': '\\n',
        '\t': '\\t',
        '\r': '\\r',
        "'": "\\'",
        '"': '\\"',
    }
    for escape_char, made_escape_char in escape_chars.items():
        text = text.replace(escape_char, made_escape_char)
    return text

def clean_escapes(text):
    escape_chars = {
        '\n': '\\n',
        '\t': '\\t',
        '\r': '\\r',
        "'": "\\'",
        '"': '\\"',
    }
    for escape_char, made_escape_char in escape_chars.items():
        text = text.replace(made_escape_char, escape_char)
    return text

def add_indent(indent):
    return indent * 4 * ' '

def _hash_widths(value):
    if isinstance(value, str) and pyRitoFile.bin.BINHasher.is_hash(value):
        return {8 if len(value) == 16 else 4}
    if isinstance(value, dict):
        widths = set()
        for key, item in value.items():
            widths.update(_hash_widths(key))
            widths.update(_hash_widths(item))
        return widths
    if isinstance(value, (list, tuple)):
        widths = set()
        for item in value:
            widths.update(_hash_widths(item))
        return widths
    return set()


def clean_type(bin_type, value=None):
    if bin_type == pyRitoFile.bin.BINType.HASH:
        widths = _hash_widths(value)
        if len(widths) > 1:
            raise ValueError('Ritobin cannot represent mixed Hash widths in one container/map side.')
        if widths == {8}:
            return 'hash[u64]'
    return bin_type.name.lower()

def hash_or_raw(name, quote=True):
    if pyRitoFile.bin.BINHasher.is_hash(name):
        return f'0x{name.lower()}'
    return f'"{name}"' if quote else name

def make_types(str_type):
    """Parse nested Ritobin types; hash width/algorithm are metadata, not BIN kinds."""
    str_type = str_type.strip().replace(' ', '')
    open_at = str_type.find('[')
    if open_at < 0:
        return [pyRitoFile.bin.BINType[str_type.upper()]]
    if not str_type.endswith(']'):
        raise ValueError(f'Invalid Ritobin type: {str_type}')
    base = str_type[:open_at].lower()
    args = _split_type_arguments(str_type[open_at + 1:-1])

    if base == 'hash':
        if len(args) == 0:
            return [pyRitoFile.bin.BINType.HASH, HashTypeSpec(4, 'fnv1a')]
        if len(args) not in (1, 2) or args[0] not in ('u32', 'u64'):
            raise ValueError(f'Invalid hash type: {str_type}')
        algorithm = args[1].lower() if len(args) == 2 else None
        if algorithm not in (None, 'fnv1a', 'xxh64', 'xxh3'):
            raise ValueError(f'Unsupported hash algorithm: {algorithm}')
        return [pyRitoFile.bin.BINType.HASH, HashTypeSpec(4 if args[0] == 'u32' else 8, algorithm)]

    kind = pyRitoFile.bin.BINType[base.upper()]
    if kind in (pyRitoFile.bin.BINType.LIST, pyRitoFile.bin.BINType.LIST2, pyRitoFile.bin.BINType.OPTION):
        if len(args) != 1:
            raise ValueError(f'{base} expects one type argument')
        return [kind, make_types(args[0])]
    if kind == pyRitoFile.bin.BINType.MAP:
        if len(args) != 2:
            raise ValueError('map expects two type arguments')
        return [kind, make_types(args[0]), make_types(args[1])]
    raise ValueError(f'{base} does not accept type arguments')

class Reader:
    def __init__(self, text):
        self.text = text
        self.cur = 0
        self.end = len(text)
    
    def human_cur(self):
        index = self.cur - 1
        if not (0 <= index < len(self.text)):
            return None, None
        line = self.text.count('\n', 0, index) + 1
        last_newline_index = self.text.rfind('\n', 0, index)
        column = index - (last_newline_index + 1) if last_newline_index != -1 else index + 1
        return f'Ln: {line}, Col: {column}'

    def read_space(self):
        text, cur, end = self.text, self.cur, self.end
        while cur < end and text[cur] in ' \n\t\r':
            cur += 1
        self.cur = cur
        if cur < end and text[cur] == '#':
            self.read_until('\n')
            self.read_space()
                   
    def read_until(self, end_char):
        text, cur, end = self.text, self.cur, self.end
        left = cur
        while cur < end and text[cur] != end_char:
            cur += 1
        right = cur
        cur += 1
        self.cur = cur
        return text[left:right]
    
    def read_exact(self, expect_char):
        char = self.text[self.cur]
        self.cur += 1
        if char != expect_char:
            raise Exception(f'ritobin: Error: Expect "{expect_char}" but got "{char}" instead at {self.human_cur()}')
    
    def read_non_quote(self):
        text, cur, end = self.text, self.cur, self.end
        left = cur
        while cur < end and text[cur] not in ' \n\t\r':
            cur += 1
        right = cur
        cur += 1
        self.cur = cur
        return text[left:right]

    def read_quote(self):
        quote = '"'
        self.read_exact(quote)
        text, cur, end = self.text, self.cur, self.end
        left = cur
        while cur < end and text[cur] != quote or (text[cur] == quote and text[cur-1] == '\\'):
            cur += 1
        right = cur
        cur += 1
        self.cur = cur
        return clean_escapes(text[left:right])

    def read_hash(self):
        return self.read_quote() if self.text[self.cur] == '"' else self.read_non_quote().removeprefix('0x')

    def read_hash_value(self, hash_spec):
        quoted = self.text[self.cur] == '"'
        raw = self.read_hash()
        width = hash_spec.width if hash_spec is not None else 4
        algorithm = hash_spec.algorithm if hash_spec is not None else 'fnv1a'
        is_numeric_hex = (
            not quoted
            and len(raw) in (8, 16)
            and all(c in '0123456789abcdefABCDEF' for c in raw)
        )
        if is_numeric_hex:
            value = int(raw, 16)
        else:
            if algorithm is None:
                raise ValueError('A quoted string cannot be converted by hash[u32/u64] without an algorithm.')
            if algorithm == 'fnv1a':
                value = int(pyRitoFile.bin.BINHasher.raw_to_hex(raw), 16)
            else:
                try:
                    import xxhash
                except ImportError as exc:
                    raise ImportError('The xxhash package is required for hash[u64,xxh64/xxh3].') from exc
                ascii_lower = raw.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))
                encoded = ascii_lower.encode('utf-8')
                value = xxhash.xxh64_intdigest(encoded) if algorithm == 'xxh64' else xxhash.xxh3_64_intdigest(encoded)
        if width == 4:
            value &= 0xffffffff
        return f'{value:0{width * 2}x}'

    def read_num(self):
        text, cur, end = self.text, self.cur, self.end
        left = cur
        while cur < end and text[cur] in '0123456789.-+e':
            cur += 1
        right = cur
        cur += 1
        self.cur = cur
        return text[left:right]
    
    def read_bool(self):
        return self.read_non_quote().lower() == 'true'
    
    def read_vector(self, vec_size):
        self.read_exact('{')
        floats = [(self.read_space(), float(self.read_num()))[1] for i in range(vec_size)]
        self.read_space()
        self.read_exact('}')
        return pyRitoFile.structs.Vector(*floats)
    
    def read_matrix(self):
        self.read_exact('{')
        floats = [(self.read_space(), float(self.read_num()))[1] for i in range(16)]
        self.read_space()
        self.read_exact('}')
        return pyRitoFile.structs.Matrix4(*floats)
    
    def read_rgba(self):
        self.read_exact('{')
        colors = [(self.read_space(), int(self.read_num()))[1] for i in range(4)]
        self.read_space()
        self.read_exact('}')
        return colors
    
    def read_list_or_list2(self, value_type):
        res = []
        self.read_exact('{')
        while self.cur < self.end:
            self.read_space()
            if self.text[self.cur] == '}':
                self.cur += 1
                break
            else:
                res.append(self.read_value(value_type))
        return res
    
    def read_pointer_or_embed(self):
        field = pyRitoFile.bin.BINField()
        field.hash_type = self.read_non_quote()
        if field.hash_type == 'null':
            field.hash_type = '00000000'
            field.data = None
        else:
            field.data = []
            self.read_space()
            self.read_exact('{')
            while self.cur < self.end:
                self.read_space()
                if self.text[self.cur] == '}':
                    self.cur += 1
                    break
                else:
                    field.data.append(self.read_field())
        return field

    def read_option(self, value_type):
        self.read_exact('{')
        if self.text[self.cur] == '}':
            self.cur += 1
            return None
        else:
            self.read_space()
            res = self.read_value(value_type)
            self.read_space()
            self.read_exact('}')
        return res
    
    def read_map(self, key_type, value_type):
        res = {}
        self.read_exact('{')
        while self.cur < self.end:
            self.read_space()
            if self.text[self.cur] == '}':
                self.cur += 1
                break
            else:
                key = self.read_value(key_type)
                self.read_space()
                self.read_exact('=')
                self.read_space()
                value = self.read_value(value_type)
                res[key] = value
        return res
    
    read_value_dict = {
        pyRitoFile.bin.BINType.NONE:       lambda: None,
        pyRitoFile.bin.BINType.BOOL:       lambda self, value_types: self.read_bool(),
        pyRitoFile.bin.BINType.I8:         lambda self, value_types: int(self.read_num()),
        pyRitoFile.bin.BINType.U8:         lambda self, value_types: int(self.read_num()),
        pyRitoFile.bin.BINType.I16:        lambda self, value_types: int(self.read_num()),
        pyRitoFile.bin.BINType.U16:        lambda self, value_types: int(self.read_num()),
        pyRitoFile.bin.BINType.I32:        lambda self, value_types: int(self.read_num()),
        pyRitoFile.bin.BINType.U32:        lambda self, value_types: int(self.read_num()),
        pyRitoFile.bin.BINType.I64:        lambda self, value_types: int(self.read_num()),
        pyRitoFile.bin.BINType.U64:        lambda self, value_types: int(self.read_num()),
        pyRitoFile.bin.BINType.F32:        lambda self, value_types: float(self.read_num()),
        pyRitoFile.bin.BINType.VEC2:       lambda self, value_types: self.read_vector(2),
        pyRitoFile.bin.BINType.VEC3:       lambda self, value_types: self.read_vector(3),
        pyRitoFile.bin.BINType.VEC4:       lambda self, value_types: self.read_vector(4),
        pyRitoFile.bin.BINType.MTX44:      lambda self, value_types: self.read_matrix(),
        pyRitoFile.bin.BINType.RGBA:       lambda self, value_types: self.read_rgba(),
        pyRitoFile.bin.BINType.STRING:     lambda self, value_types: self.read_quote(),
        pyRitoFile.bin.BINType.HASH:       lambda self, value_types: self.read_hash(),
        pyRitoFile.bin.BINType.FILE:       lambda self, value_types: self.read_hash(),
        pyRitoFile.bin.BINType.LIST:       lambda self, value_types: self.read_list_or_list2(value_types[1]),
        pyRitoFile.bin.BINType.LIST2:      lambda self, value_types: self.read_list_or_list2(value_types[1]),
        pyRitoFile.bin.BINType.POINTER:    lambda self, value_types: self.read_pointer_or_embed(),
        pyRitoFile.bin.BINType.EMBED:      lambda self, value_types: self.read_pointer_or_embed(),
        pyRitoFile.bin.BINType.OPTION:     lambda self, value_types: self.read_option(value_types[1]),
        pyRitoFile.bin.BINType.MAP:        lambda self, value_types: self.read_map(value_types[1], value_types[2]),
        pyRitoFile.bin.BINType.LINK:       lambda self, value_types: self.read_hash(),
        pyRitoFile.bin.BINType.FLAG:       lambda self, value_types: self.read_bool(),
    }

    def read_value(self, value_types):
        if isinstance(value_types, pyRitoFile.bin.BINType):
            value_types = [value_types]
        value_type = value_types[0]
        if value_type == pyRitoFile.bin.BINType.HASH:
            spec = value_types[1] if len(value_types) > 1 else HashTypeSpec()
            return self.read_hash_value(spec)
        if value_type in (pyRitoFile.bin.BINType.LIST, pyRitoFile.bin.BINType.LIST2):
            return self.read_list_or_list2(value_types[1])
        if value_type == pyRitoFile.bin.BINType.OPTION:
            return self.read_option(value_types[1])
        if value_type == pyRitoFile.bin.BINType.MAP:
            return self.read_map(value_types[1], value_types[2])
        return self.read_value_dict[value_type](self, value_types)
    
    def read_field(self):
        self.read_space()
        field = pyRitoFile.bin.BINField()
        # hash
        field.hash = self.read_hash().rstrip(':')
        self.read_space()
        # type
        str_type = self.read_non_quote()
        field_types = make_types(str_type)
        self.read_space()
        self.read_exact('=')
        self.read_space()
        # data
        field.data = self.read_value(field_types)
        # update field
        field.type = field_types[0]
        if field.type in (pyRitoFile.bin.BINType.LIST, pyRitoFile.bin.BINType.LIST2, pyRitoFile.bin.BINType.OPTION):
            # The type spec may include hash[u64]; BINField stores the primitive kind.
            field.value_type = field_types[1][0]
        elif field.type in (pyRitoFile.bin.BINType.POINTER, pyRitoFile.bin.BINType.EMBED):
            # set hash type for embed & pointer
            # life hack: read value return a new field 
            # so we set that new field attributes to current field directly
            field.hash_type = field.data.hash_type
            field.data = field.data.data
        elif field.type == pyRitoFile.bin.BINType.MAP:
            # set key, value kind for map; hash width is preserved in each hex value
            field.key_type = field_types[1][0]
            field.value_type = field_types[2][0]
        return field
        
    def read_entry(self):
        self.read_space()
        entry = pyRitoFile.bin.BINEntry()
        # hash
        entry.hash = self.read_hash()
        self.read_space()
        self.read_exact('=')
        self.read_space()
        # type
        entry.type = self.read_hash()
        # rd data
        entry.data = []
        self.read_exact('{')
        while self.cur < self.end:
            self.read_space()
            if self.text[self.cur] == '}':
                self.cur += 1
                break
            else:
                entry.data.append(self.read_field())
        return entry

    def read_header_type(self, bin):
        # pointless because we hardcode writing header in pyRitoFile
        self.read_until('=')
        self.read_space()
        bin.signature = self.read_value(make_types('string'))
        if bin.signature == 'PTCH':
            bin.is_patch = True

    def read_header_version(self, bin):
        # pointless because we hardcode writing header in pyRitoFile
        self.read_until('=')
        self.read_space()
        bin.version = self.read_value(make_types('u32'))

    def read_links(self, bin):
        self.read_until('=')
        self.read_space()
        bin.links = self.read_value(make_types('list[string]'))

    def read_entries(self, bin):
        self.read_until('=')
        self.read_space()

        bin.entries = []
        self.read_exact('{')
        while self.cur < self.end:
            self.read_space()
            if self.text[self.cur] == '}':
                self.cur += 1
                break
            else:
                bin.entries.append(self.read_entry())

    def read_patch(self):
        self.read_space()
        patch = pyRitoFile.bin.BINPatch()
        # hash
        patch.hash = self.read_hash()
        self.read_space()
        self.read_exact('=')
        self.read_space()
        self.read_non_quote()
        self.read_space()
        self.read_exact('{')
        self.read_space()
        # path
        self.read_until('=')
        self.read_space()
        patch.path = self.read_quote()
        self.read_space()
        # type
        self.read_non_quote()
        self.read_space()
        str_type = self.read_non_quote()
        field_types = make_types(str_type)
        patch.type = field_types[0]
        self.read_space()
        self.read_exact('=')
        self.read_space()
        # data
        if field_types[0] in (pyRitoFile.bin.BINType.LIST, pyRitoFile.bin.BINType.LIST2,
                              pyRitoFile.bin.BINType.OPTION, pyRitoFile.bin.BINType.MAP):
            field = pyRitoFile.bin.BINField()
            field.type = field_types[0]
            if field.type == pyRitoFile.bin.BINType.MAP:
                field.key_type = field_types[1][0]
                field.value_type = field_types[2][0]
            else:
                field.value_type = field_types[1][0]
            field.data = self.read_value(field_types)
            patch.data = field
        else:
            patch.data = self.read_value(field_types)
        self.read_space()
        self.read_exact('}')
        return patch

    def read_patches(self, bin):
        self.read_until('=')
        self.read_space()

        bin.patches = []
        self.read_exact('{')
        while self.cur < self.end:
            self.read_space()
            if self.text[self.cur] == '}':
                self.cur += 1
                break
            else:
                bin.patches.append(self.read_patch())

    def read_blocks(self):
        blocks_to_commands = {
            'type': self.read_header_type,
            'version': self.read_header_version,
            'linked': self.read_links,
            'entries': self.read_entries,
            'patches': self.read_patches,
        }
        max_chars_to_read = max(len(block_header) for block_header in blocks_to_commands)
        res = ''
        while self.cur < self.end and len(res) < max_chars_to_read and res not in blocks_to_commands:
            res += self.text[self.cur]
            self.cur += 1
        if res not in blocks_to_commands:
            raise Exception(f'ritobin: Error: Unexpected block header: {res} at {self.human_cur()}')
        return blocks_to_commands[res]

    def read_text(self):
        bin = pyRitoFile.bin.BIN()
        bin.links = []
        bin.entries = []
        while self.cur < self.end:
            self.read_space()
            self.read_blocks()(bin)
            self.read_space()
        return bin

class Writer:  
    def __init__(self, bin):
        self.bin = bin

    def write_header(self, indent):
        text = f'{add_indent(indent)}#{self.bin.signature}_text\n'
        text += f'{add_indent(indent)}type: string = "{self.bin.signature}"\n'
        text += f'{add_indent(indent)}version: u32 = {self.bin.version}\n'
        return text
    
    def write_links(self, indent):
        text = f'{add_indent(indent)}linked: list[string] = {{'
        if len(self.bin.links) > 0:
            text += '\n'
            for link in self.bin.links:
                text += f'{add_indent(indent+1)}"{link}"\n'
            text += f'{add_indent(indent)}}}\n'
        else:
            text += '}\n'
        return text
    
    def write_value(self, value, value_type, indent, inline=True):
        # complex
        if value_type in (pyRitoFile.bin.BINType.LIST, pyRitoFile.bin.BINType.LIST2):
            text = ''
            for v in value.data:
                text += self.write_value(v, value_type, indent, inline=False)
            return text
        elif value_type in (pyRitoFile.bin.BINType.EMBED, pyRitoFile.bin.BINType.POINTER):
            if value.hash_type == '00000000':
                text = f'{add_indent(0 if inline else indent)}null'
            else:
                text = f'{add_indent(0 if inline else indent)}{hash_or_raw(value.hash_type, quote=False)} {{'
                if value.data != None and len(value.data) > 0:
                    text += '\n'
                    for f in value.data:
                        text += self.write_field(f, indent+1)
                    text += f'{add_indent(indent)}}}'
                else:
                    text += '}'
            return text
        # basic
        elif value_type == pyRitoFile.bin.BINType.STRING:
            return f'{add_indent(0 if inline else indent)}"{make_escapes(value)}"'
        elif value_type in (pyRitoFile.bin.BINType.HASH, pyRitoFile.bin.BINType.LINK, pyRitoFile.bin.BINType.FILE):
            return f'{add_indent(0 if inline else indent)}{hash_or_raw(value)}'
        elif value_type == pyRitoFile.bin.BINType.BOOL:
            return f'{add_indent(0 if inline else indent)}{value}'.lower()
        elif value_type == pyRitoFile.bin.BINType.FLAG:
            return f'{add_indent(0 if inline else indent)}{value != 0}'.lower()
        elif value_type == pyRitoFile.bin.BINType.F32:
            return f'{add_indent(0 if inline else indent)}{f32_str(value)}'
        elif value_type in (pyRitoFile.bin.BINType.VEC2, pyRitoFile.bin.BINType.VEC3, pyRitoFile.bin.BINType.VEC4, pyRitoFile.bin.BINType.RGBA):
            values = ', '.join(f'{f32_str(v)}' for v in value)
            return f'{add_indent(0 if inline else indent)}{{ {values} }}'
        elif value_type in (pyRitoFile.bin.BINType.I8, pyRitoFile.bin.BINType.U8,pyRitoFile.bin.BINType.I16,pyRitoFile.bin.BINType.U16,pyRitoFile.bin.BINType.I32,pyRitoFile.bin.BINType.U32,pyRitoFile.bin.BINType.I64,pyRitoFile.bin.BINType.U64):
            return f'{add_indent(0 if inline else indent)}{value}'
        else:
            print(value_type + ' is not sp yet')
    
    def write_list_or_list2(self, field, indent):
        text = f'{add_indent(indent)}{hash_or_raw(field.hash, quote=False)}: {clean_type(field.type)}[{clean_type(field.value_type, field.data)}] = {{'
        if len(field.data) > 0:
            text += '\n'
            for value in field.data:
                text += f'{self.write_value(value, field.value_type, indent+1, inline=False)}\n'
            text += f'{add_indent(indent)}}}\n'
        else:
            text += '}\n'
        return text
    
    def write_pointer_or_embed(self, field, indent):
        if field.hash_type == '00000000':
            text = f'{add_indent(indent)}{hash_or_raw(field.hash, quote=False)}: {clean_type(field.type)} = null\n'
        else:
            text = f'{add_indent(indent)}{hash_or_raw(field.hash, quote=False)}: {clean_type(field.type)} = {hash_or_raw(field.hash_type, quote=False)} {{'
            if field.data != None and len(field.data) > 0:
                text += '\n'
                for field in field.data:
                    text += self.write_field(field, indent+1)
                text += f'{add_indent(indent)}}}\n'
            else:
                text += '}\n'
        return text

    def write_option(self, field, indent):
        text = f'{add_indent(indent)}{hash_or_raw(field.hash, quote=False)}: {clean_type(field.type)}[{clean_type(field.value_type, field.data)}] = {{'
        if field.data != None:
            text += '\n'
            text += f'{self.write_value(field.data, field.value_type, indent+1, inline=False)}\n'
            text += f'{add_indent(indent)}}}\n'
        else:
            text += '}\n'
        return text

    def write_map(self, field, indent):
        text = f'{add_indent(indent)}{hash_or_raw(field.hash, quote=False)}: {clean_type(field.type)}[{clean_type(field.key_type, list(field.data.keys()))},{clean_type(field.value_type, list(field.data.values()))}] = {{'
        if len(field.data) > 0:
            text += '\n'
            for key, value in field.data.items():
                text += f'{self.write_value(key, field.key_type, indent+1, inline=False)} = {self.write_value(value, field.value_type, indent+1, inline=True)}\n'
            text += f'{add_indent(indent)}}}\n'
        else:
            text += '}\n'
        return text

    def write_matrix(self, field, indent):
        matrix = field.data
        text = f'{add_indent(indent)}{hash_or_raw(field.hash, quote=False)}: {clean_type(field.type)} = {{\n'
        text += f'{add_indent(indent+1)}{f32_str(matrix.a)}, {f32_str(matrix.b)}, {f32_str(matrix.c)}, {f32_str(matrix.d)}\n'
        text += f'{add_indent(indent+1)}{f32_str(matrix.e)}, {f32_str(matrix.f)}, {f32_str(matrix.g)}, {f32_str(matrix.h)}\n'
        text += f'{add_indent(indent+1)}{f32_str(matrix.i)}, {f32_str(matrix.j)}, {f32_str(matrix.k)}, {f32_str(matrix.l)}\n'
        text += f'{add_indent(indent+1)}{f32_str(matrix.m)}, {f32_str(matrix.n)}, {f32_str(matrix.o)}, {f32_str(matrix.p)}\n'
        text += f'{add_indent(indent)}}}\n'
        return text
    
    def write_field(self, field, indent):
        if field.type in (pyRitoFile.bin.BINType.LIST, pyRitoFile.bin.BINType.LIST2):
            text = self.write_list_or_list2(field, indent)
        elif field.type in (pyRitoFile.bin.BINType.POINTER, pyRitoFile.bin.BINType.EMBED):
            text = self.write_pointer_or_embed(field, indent)
        elif field.type == pyRitoFile.bin.BINType.OPTION:
            text = self.write_option(field, indent)
        elif field.type == pyRitoFile.bin.BINType.MAP:
            text = self.write_map(field, indent)
        elif field.type == pyRitoFile.bin.BINType.MTX44:
            text = self.write_matrix(field, indent)
        else:
            text = f'{add_indent(indent)}{hash_or_raw(field.hash, quote=False)}: {clean_type(field.type, field.data)} = {self.write_value(field.data, field.type, indent)}\n'
        return text
    
    def write_entry(self, entry, indent):
        text = f'{add_indent(indent)}{hash_or_raw(entry.hash)} = {hash_or_raw(entry.type, quote=False)} {{'
        if len(entry.data) > 0:
            text += '\n'
            for field in entry.data:
                text += self.write_field(field, indent+1)
            text += f'{add_indent(indent)}}}\n'
        else:
            text += '}\n'
        return text

    def write_entries(self, indent):
        text = f'{add_indent(indent)}entries: map[hash,embed] = {{'
        if len(self.bin.entries) > 0:
            text += '\n'
            for entry in self.bin.entries:
                text += self.write_entry(entry, indent+1)
            text += f'{add_indent(indent)}}}\n'
        else:
            text += '}\n'
        return text
    
    def write_patches(self, indent):
        text = f'{add_indent(indent)}patches: map[hash,embed] = {{'
        if len(self.bin.patches) > 0:
            text += '\n'
            for entry in self.bin.patches:
                text += self.write_patch(entry, indent+1)
            text += f'{add_indent(indent)}}}\n'
        else:
            text += '}\n'
        return text
    
    def write_patch(self, patch, indent):
        text = f'{add_indent(indent)}{hash_or_raw(patch.hash)} = patch {{\n'
        text += f'{add_indent(indent+1)}path: string = "{patch.path}"\n'
        text += f'{add_indent(indent+1)}value: '
        if patch.type in (pyRitoFile.bin.BINType.LIST, pyRitoFile.bin.BINType.LIST2):
            field = patch.data
            text += f'{add_indent(0)}{clean_type(field.type)}[{clean_type(field.value_type, field.data)}] = {{'
            if len(field.data) > 0:
                text += '\n'
                for value in field.data:
                    text += f'{self.write_value(value, field.value_type, indent+2, inline=False)}\n'
                text += f'{add_indent(indent+1)}}}\n'
            else:
                text += '}\n'
        elif patch.type == pyRitoFile.bin.BINType.OPTION:
            field = patch.data
            text += f'{add_indent(0)}option[{clean_type(field.value_type, field.data)}] = {{'
            if field.data is not None:
                text += '\n'
                text += f'{self.write_value(field.data, field.value_type, indent+2, inline=False)}\n'
                text += f'{add_indent(indent+1)}}}\n'
            else:
                text += '}\n'
        elif patch.type == pyRitoFile.bin.BINType.MAP:
            field = patch.data
            key_type = clean_type(field.key_type, list(field.data.keys()))
            value_type = clean_type(field.value_type, list(field.data.values()))
            text += f'{add_indent(0)}map[{key_type},{value_type}] = {{'
            if field.data:
                text += '\n'
                for key, value in field.data.items():
                    text += f'{self.write_value(key, field.key_type, indent+2, inline=False)} = {self.write_value(value, field.value_type, indent+2, inline=True)}\n'
                text += f'{add_indent(indent+1)}}}\n'
            else:
                text += '}\n'
        elif patch.type in (pyRitoFile.bin.BINType.POINTER, pyRitoFile.bin.BINType.EMBED):
            field = patch.data
            if field.hash_type == '00000000':
                text += f'{add_indent(0)}{clean_type(patch.type)} = null\n'
            else:
                text += f'{add_indent(0)}{clean_type(patch.type)} = {hash_or_raw(field.hash_type, quote=False)} {{'
                if field.data != None and len(field.data) > 0:
                    text += '\n'
                    for f in field.data:
                        text += self.write_field(f, indent+2)
                    text += f'{add_indent(indent+1)}}}\n'
                else:
                    text += '}\n'
        elif patch.type == pyRitoFile.bin.BINType.MTX44:
            matrix = patch.data
            text += f'{add_indent(0)}{clean_type(patch.type)} = {{\n'
            text += f'{add_indent(indent+2)}{f32_str(matrix.a)}, {f32_str(matrix.b)}, {f32_str(matrix.c)}, {f32_str(matrix.d)}\n'
            text += f'{add_indent(indent+2)}{f32_str(matrix.e)}, {f32_str(matrix.f)}, {f32_str(matrix.g)}, {f32_str(matrix.h)}\n'
            text += f'{add_indent(indent+2)}{f32_str(matrix.i)}, {f32_str(matrix.j)}, {f32_str(matrix.k)}, {f32_str(matrix.l)}\n'
            text += f'{add_indent(indent+2)}{f32_str(matrix.m)}, {f32_str(matrix.n)}, {f32_str(matrix.o)}, {f32_str(matrix.p)}\n'
            text += f'{add_indent(indent+1)}}}\n'
        else:
            text += f'{clean_type(patch.type, patch.data)} = {self.write_value(patch.data, patch.type, indent)}\n'
        text += f'{add_indent(indent)}}}\n'
        return text

    def write_bin(self, indent):
        text = self.write_header(indent)
        text += self.write_links(indent)
        text += self.write_entries(indent)
        if self.bin.is_patch:
            text += self.write_patches(indent)
        return text


def text_to_bin(text_path, bin_path=None):
    if bin_path == None:
        bin_path = '.'.join(text_path.split('.')[:-1] + ['.bin'])
    with pyRitoFile.stream.StringStream.reader(text_path) as ss:
        Reader(ss.read()).read_text().write(bin_path)
    

def bin_to_text(bin_path, text_path=None, hashtables=None):
    if text_path == None:
        text_path = lepath.ext(bin_path, '.bin', '.py')
    bin = pyRitoFile.bin.BIN().read(bin_path)
    if hashtables != None:
        bin.un_hash(hashtables)
    with pyRitoFile.stream.StringStream.writer(text_path) as ss:
        ss.write(Writer(bin).write_bin(0))