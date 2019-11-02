import struct 
import json 
import codecs
import io
from collections import OrderedDict
BRKFILEMAGIC = b"J3D1brk1"
PADDING = b"This is padding data to align"

def read_uint32(f):
    return struct.unpack(">I", f.read(4))[0]
def read_uint16(f):
    return struct.unpack(">H", f.read(2))[0]
def read_sint16(f):
    return struct.unpack(">h", f.read(2))[0]
def read_uint8(f):
    return struct.unpack(">B", f.read(1))[0]
def read_sint8(f):
    return struct.unpack(">b", f.read(1))[0]
def read_float(f):
    return struct.unpack(">f", f.read(4))[0]
    
    
def write_uint32(f, val):
    f.write(struct.pack(">I", val))
def write_uint16(f, val):
    f.write(struct.pack(">H", val))
def write_sint16(f, val):
    f.write(struct.pack(">h", val))
def write_uint8(f, val):
    f.write(struct.pack(">B", val))
def write_sint8(f, val):
    f.write(struct.pack(">b", val))
def write_float(f, val):
    f.write(struct.pack(">f", val))


def write_padding(f, multiple):
    next_aligned = (f.tell() + (multiple - 1)) & ~(multiple - 1)
    
    diff = next_aligned - f.tell()
    
    for i in range(diff):
        pos = i%len(PADDING)
        f.write(PADDING[pos:pos+1])


# Optional rounding
def opt_round(val, digits):
    if digits is None:
        return val
    else:
        return round(val, digits)


def write_indented(f, text, level):
    f.write(" "*level)
    f.write(text)
    f.write("\n")


# Find the start of the sequence seq in the list in_list, if the sequence exists
def find_sequence(in_list, seq):
    matchup = 0
    start = -1

    found = False
    started = False

    for i in range(0, len(in_list)-len(seq)+1):
        for j in range(len(seq)):
            #print(in_list[i+j], seq[j])
            if in_list[i+j] == seq[j]:
                print("match", in_list[i+j], seq[j])
                if j == len(seq)-1:
                    start = i
                    found = True 
                    break 
            else:
                print("nop")
                start = -1 
                break 
        if found:
            break
            
    if not found:
        start = -1


    return start
    

def find_single_value(in_list, value):
    
    return find_sequence(in_list, [value])
    
    
class StringTable(object):
    def __init__(self):
        self.strings = []
    
    @classmethod
    def from_file(cls, f):
        stringtable = cls()
        
        start = f.tell()
        
        string_count = read_uint16(f)
        f.read(2) # 0xFFFF
        
        offsets = []
        
        print("string count", string_count)
        
        for i in range(string_count):
            hash = read_uint16(f)
            string_offset = read_uint16(f)
            
            offsets.append(string_offset)
        
        for offset in offsets:
            f.seek(start+offset)
            
            # Read 0-terminated string 
            string_start = f.tell()
            string_length = 0
            
            while f.read(1) != b"\x00":
                string_length += 1 
            
            f.seek(start+offset)
            
            if string_length == 0:
                stringtable.strings.append("")
            else:
                stringtable.strings.append(f.read(string_length).decode("shift-jis"))
            
        return stringtable 
            
    def hash_string(self, string):
        hash = 0
        
        for char in string:
            hash *= 3 
            hash += ord(char)
            hash = 0xFFFF & hash  # cast to short 
        
        return hash

    def write(self, f):
        start = f.tell()
        f.write(struct.pack(">HH", len(self.strings), 0xFFFF))
        
        for string in self.strings:
            hash = self.hash_string(string)
            
            f.write(struct.pack(">HH", hash, 0xABCD))
        
        offsets = []
        
        for string in self.strings:
            offsets.append(f.tell())
            f.write(string.encode("shift-jis"))
            f.write(b"\x00")

        end = f.tell()

        for i, offset in enumerate(offsets):
            f.seek(start+4 + (i*4) + 2)
            write_uint16(f, offset-start)

        f.seek(end)
        
class AnimComponent(object):
    def __init__(self, time, value, tangentIn, tangentOut=None):
        self.time = time 
        self.value = value
        self.tangentIn = tangentIn 
        
        if tangentOut is None:
            self.tangentOut = tangentIn
        else:
            self.tangentOut = tangentOut
    
    def serialize(self):
        return [self.time, self.value, self.tangentIn, self.tangentOut]
    
    def __repr__(self):
        return "Time: {0}, Val: {1}, TanIn: {2}, TanOut: {3}".format(self.time, self.value, self.tangentIn, self.tangentOut).__repr__()
        
    @classmethod
    def from_array(cls, offset, index, count, valarray, tanType):
        if count == 1:
            return cls(0, valarray[offset+index], 0, 0)
            
        
        else:
            print("TanType:", tanType)
            print(len(valarray), offset+index*4)
            
            if tanType == 0:
                return cls(valarray[offset + index*3], valarray[offset + index*3 + 1], valarray[offset + index*3 + 2])
            elif tanType == 1:
                return cls(valarray[offset + index*4], valarray[offset + index*4 + 1], valarray[offset + index*4 + 2], valarray[offset + index*4 + 3])
            else:
                raise RuntimeError("unknown tangent type: {0}".format(tanType))


class ColorAnimation(object):
    def __init__(self, index, name, unknown=0):
        self._index = index 
        #self.matindex = matindex 
        self.name = name 
        self.unknown = unknown 
        
        self.component = {"R": [], "G": [], "B": [], "A": []}

        self._component_offsets = {}
        self._tangent_type = {"R": 1, "G": 1, "B": 1, "A": 1}

    def add_component(self, colorcomp, animcomp):
        self.component[colorcomp].append(animcomp)
    
    @classmethod
    def from_brk(cls, f, name, index, rgba_arrays):
        coloranim = cls(name, index)
        
        for i, comp in enumerate(("R", "G", "B", "A")):
            count, offset, tangent_type = struct.unpack(">HHH", f.read(6)) 
            
            for j in range(count):
                animcomp = AnimComponent.from_array(offset, j, count, rgba_arrays[i], tangent_type)
                coloranim.add_component(comp, animcomp)
        
        unknown = read_uint8(f)
        coloranim.unknown = unknown
        assert f.read(3) == b"\xFF\xFF\xFF"
        
        return coloranim
        
    # These functions are used for keeping track of the offset
    # in the json->brk conversion and are otherwise not useful.
    def _set_component_offsets(self, colorcomp, val):
        self._component_offsets[colorcomp] = val
    
    def _set_tangent_type(self, colorcomp, val):
        self._tangent_type[colorcomp] = val


class BRKAnim(object):
    def __init__(self, loop_mode, duration):
        self.register_animations = []
        self.constant_animations = []
        self.loop_mode = loop_mode
        #self.anglescale = anglescale
        self.duration = duration
        #self.unknown_address = unknown_address
    
    def dump(self, f, digits=None):
        write_indented(f, "{", level=0)

        write_indented(f, "\"loop_mode\": {},".format(self.loop_mode), level=4)
        #write_indented(f, "\"angle_scale\": {},".format(self.anglescale), level=4)
        write_indented(f, "\"duration\": {},".format(self.duration), level=4)
        #write_indented(f, "\"unknown\": \"0x{:x}\",".format(self.unknown_address), level=4)
        write_indented(f, "", level=4)
        
        for animtype, animations in (
            ("register", self.register_animations), 
            ("constant", self.constant_animations)
            ):
            write_indented(f, "\"{0}_color_animations\": [".format(animtype), level=4)

            for i, animation in enumerate(animations):
                write_indented(f, "{", level=8)

                write_indented(f, "\"material_name\": \"{}\",".format(animation.name), level=12)
                write_indented(f, "\"unknown\": {},".format(animation.unknown), level=12)

                write_indented(f, "", level=12)
                for component_name in ("red", "green", "blue", "alpha"):
                    comp = component_name[0].upper()
                    write_indented(f, "\"{}\": [".format(component_name), level=12)
                    total_count = len(animation.component[comp])
                    for j, animcomp in enumerate(animation.component[comp]):
                        if j < total_count-1:
                            write_indented(f, str(animcomp.serialize())+",",  level=16)
                        else:
                            write_indented(f, str(animcomp.serialize()),  level=16)
                            
                    if component_name != "alpha":
                        write_indented(f, "],", level=12)
                    else:
                        write_indented(f, "]", level=12)
                    
                if i < len(animations)-1:
                    write_indented(f, "},", level=8)
                else:
                    write_indented(f, "}", level=8)
            if animtype != "constant":
                write_indented(f, "],", level=4)
            else:
                write_indented(f, "]", level=4)
        write_indented(f, "}", level=0)

    def write_brk(self, f):
        f.write(BRKFILEMAGIC)
        filesize_offset = f.tell()
        f.write(b"ABCD") # Placeholder for file size
        write_uint32(f, 1) # Always a section count of 1
        f.write(b"SVR1" + b"\xFF"*12)

        trk1_start = f.tell()
        f.write(b"TRK1")

        trk1_size_offset = f.tell()
        f.write(b"EFGH")  # Placeholder for trk1 size
        write_uint8(f, self.loop_mode)
        write_uint8(f, 0xFF)
        
        write_uint16(f, self.duration)
        write_uint16(f, len(self.register_animations))
        write_uint16(f, len(self.constant_animations))
        
        count_offset = f.tell()
        f.write(b"AB"*8)  # Placeholder for register and constant rgba counts
        data_offsets = f.tell()
        f.write(b"ABCD"*6) # Placeholder for data offsets 
        f.write(b"ABCD"*8) # Placeholder for rgba data offsets
        
        write_padding(f, multiple=32)
        assert f.tell() == 0x80
        
        
        register_anim_start = f.tell()
        f.write(b"\x00"*(0x1C*len(self.register_animations)))
        write_padding(f, multiple=4)
        
        constant_anim_start = f.tell()
        f.write(b"\x00"*(0x1C*len(self.constant_animations)))
        write_padding(f, multiple=4)
        


        
        all_values = {}
        
        for animtype, animations in (
        ("register", self.register_animations), 
        ("constant", self.constant_animations)):
        
            all_values[animtype] = {}
            for colorcomp in ("R", "G", "B", "A"):
                all_values[animtype][colorcomp] = []
                
                for anim in animations: 
                    
                
                    animation_components = anim.component[colorcomp]
                    """
                    use_tantype_1 = False 
                    for comp in animation_components:
                        if comp.tangentIn != comp.tangentOut:
                            use_tantype_1 = True 
                            break 
                    
                    if not use_tantype_1:
                        anim._set_tangent_type(colorcomp, 0)"""
                        
                    # Set up offset for scale
                    if len(animation_components) == 1:
                        sequence = [animation_components[0].value]
                    else:
                        sequence = []
                        for comp in animation_components:
                            sequence.append(comp.time)
                            sequence.append(comp.value)
                            sequence.append(comp.tangentIn)
                            sequence.append(comp.tangentOut)
                    
                    offset = find_sequence(all_values[animtype][colorcomp],sequence)
                    print("curr sequence:", all_values[animtype][colorcomp])
                    print("to find sequence:", sequence)
                    print("found it?", offset)
                    if offset == -1:
                        offset = len(all_values[animtype][colorcomp])
                        all_values[animtype][colorcomp].extend(sequence)
                        
                    anim._set_component_offsets(colorcomp, offset)

        data_starts = []
        for animtype in ("register", "constant"):
            
            for comp in ("R", "G", "B", "A"):
                data_starts.append(f.tell())
                for val in all_values[animtype][comp]:
                    write_sint16(f, val)
                write_padding(f, 4)
                
                
        # Write the indices for each animation
        register_index_start = f.tell()
        for i in range(len(self.register_animations)):
            write_uint16(f, i)
        write_padding(f, multiple=4)
        
        constant_index_start = f.tell()
        for i in range(len(self.constant_animations)):
            write_uint16(f, i)
        write_padding(f, multiple=4)
        
        
        # Create string table of material names for register color animations
        register_stringtable = StringTable()

        for anim in self.register_animations:
            register_stringtable.strings.append(anim.name)
        
        # Create string table of material names for constant color animations
        constant_stringtable = StringTable()

        for anim in self.constant_animations:
            constant_stringtable.strings.append(anim.name)
        
        register_stringtable_start = f.tell()
        register_stringtable.write(f)
        write_padding(f, multiple=4)
        
        constant_stringtable_start = f.tell()
        constant_stringtable.write(f)
        write_padding(f, multiple=4)
        
        write_padding(f, multiple=32)
        total_size = f.tell()

        f.seek(register_anim_start)
        for anim in self.register_animations:
            for comp in ("R", "G", "B", "A"):
                write_uint16(f, len(anim.component[comp])) # Scale count for this animation
                write_uint16(f, anim._component_offsets[comp]) # Offset into scales
                write_uint16(f, anim._tangent_type[comp]) # Tangent type, 0 = only TangentIn; 1 = TangentIn and TangentOut

            write_uint8(f, anim.unknown)
            f.write(b"\xFF\xFF\xFF")
        
        f.seek(constant_anim_start)
        for anim in self.constant_animations:
            for comp in ("R", "G", "B", "A"):
                write_uint16(f, len(anim.component[comp])) # Scale count for this animation
                write_uint16(f, anim._component_offsets[comp]) # Offset into scales
                write_uint16(f, anim._tangent_type[comp]) # Tangent type, 0 = only TangentIn; 1 = TangentIn and TangentOut

            write_uint8(f, anim.unknown)
            f.write(b"\xFF\xFF\xFF")
        
        
        # Fill in all the placeholder values
        f.seek(filesize_offset)
        write_uint32(f, total_size)

        f.seek(trk1_size_offset)
        write_uint32(f, total_size - trk1_start)

        f.seek(count_offset)
        for animtype in ("register", "constant"):
            for comp in ("R", "G", "B", "A"):
                write_uint16(f, len(all_values[animtype][comp]))
                
        # Next come the section offsets
        write_uint32(f, register_anim_start        - trk1_start)
        write_uint32(f, constant_anim_start        - trk1_start)
        write_uint32(f, register_index_start       - trk1_start)
        write_uint32(f, constant_index_start       - trk1_start)
        write_uint32(f, register_stringtable_start - trk1_start)
        write_uint32(f, constant_stringtable_start - trk1_start)
        
        # RGBA data starts 
        for data_start in data_starts:
            write_uint32(f, data_start - trk1_start)

    @classmethod
    def from_json(cls, f):
        brkanimdata = json.load(f)

        brk = cls(
            brkanimdata["loop_mode"],
            brkanimdata["duration"]
        )
        
        for i, animation in enumerate(brkanimdata["register_color_animations"]):
            coloranim = ColorAnimation(
                i, 
                animation["material_name"], 
                animation["unknown"])
            
            for compname in ("red", "green", "blue", "alpha"):
                comp = compname[0].upper()
                
                for colorcomp in animation[compname]:
                    coloranim.add_component(comp, AnimComponent(*colorcomp))
            
            brk.register_animations.append(coloranim)
        
        for i, animation in enumerate(brkanimdata["constant_color_animations"]):
            coloranim = ColorAnimation(
                i, 
                animation["material_name"], 
                animation["unknown"])
            
            for compname in ("red", "green", "blue", "alpha"):
                comp = compname[0].upper()
                
                for colorcomp in animation[compname]:
                    coloranim.add_component(comp, AnimComponent(*colorcomp))
            
            brk.constant_animations.append(coloranim)

        return brk

    @classmethod
    def from_brk(cls, f):
        header = f.read(8)
        if header != BRKFILEMAGIC:
            raise RuntimeError("Invalid header. Expected {} but found {}".format(BRKFILEMAGIC, header))

        size = read_uint32(f)
        print("Size of brk: {} bytes".format(size))
        sectioncount = read_uint32(f)
        assert sectioncount == 1

        svr_data = f.read(16)
        
        trk_start = f.tell()
        
        trk_magic = f.read(4)
        trk_sectionsize = read_uint32(f)

        loop_mode = read_uint8(f)
        padd = f.read(1)
        assert padd == b"\xFF"
        duration = read_uint16(f)
        brk = cls(loop_mode, duration)

        register_color_anim_count = read_uint16(f)
        constant_color_anim_count = read_uint16(f)
        print(register_color_anim_count, "register color anims and", constant_color_anim_count, "constant collor anims")
        component_counts = {}
        for animtype in ("register", "constant"):
            component_counts[animtype] = {}
            
            for comp in ("R", "G", "B", "A"):
                component_counts[animtype][comp] = read_uint16(f)
                print(animtype, comp, "count:", component_counts[animtype][comp])
        
        register_color_animation_offset  = read_uint32(f) + trk_start    # 
        constant_color_animation_offset  = read_uint32(f) + trk_start    #
        register_index_offset            = read_uint32(f) + trk_start    # 
        constant_index_offset            = read_uint32(f) + trk_start    # 
        register_stringtable_offset      = read_uint32(f) + trk_start    #
        constant_stringtable_offset      = read_uint32(f) + trk_start    # 

        offsets = {}
        for animtype in ("register", "constant"):
            offsets[animtype] = {}
            for comp in ("R", "G", "B", "A"):
                offsets[animtype][comp] = read_uint32(f) + trk_start 
                print(animtype, comp, "offset:", offsets[animtype][comp])
    
        print(hex(register_index_offset))
        # Read indices
        register_indices = []
        f.seek(register_index_offset)
        for i in range(register_color_anim_count):
            index = read_uint16(f)
            if i != index:
                print("warning: register index mismatch:", i, index)
                assert(False)
            register_indices.append(index)
        
        constant_indices = []
        f.seek(constant_index_offset)
        for i in range(constant_color_anim_count):
            index = read_uint16(f)
            if i != index:
                print("warning: constant index mismatch:", i, index)
                assert(False)
            constant_indices.append(index)
        
        # Read stringtable 
        f.seek(register_stringtable_offset)
        register_stringtable = StringTable.from_file(f)
        
        f.seek(constant_stringtable_offset)
        constant_stringtable = StringTable.from_file(f)
        
        # read RGBA values 
        values = {}
        for animtype in ("register", "constant"):
            values[animtype] = {}
            
            for comp in ("R", "G", "B", "A"):
                values[animtype][comp] = []
                count = component_counts[animtype][comp]
                f.seek(offsets[animtype][comp])
                print(animtype, comp, hex(offsets[animtype][comp]), count)
                for i in range(count):
                    values[animtype][comp].append(read_sint16(f))
        
        for i in range(register_color_anim_count):
            f.seek(register_color_animation_offset + 0x1C*i)
            name = register_stringtable.strings[i]
            anim = ColorAnimation.from_brk(f, i, name, (
                values["register"]["R"], values["register"]["G"], values["register"]["B"], values["register"]["A"]
                ))
            
            brk.register_animations.append(anim)
        
        for i in range(constant_color_anim_count):
            f.seek(constant_color_animation_offset + 0x1C*i)
            name = constant_stringtable.strings[i]
            anim = ColorAnimation.from_brk(f, i, name, (
                values["constant"]["R"], values["constant"]["G"], values["constant"]["B"], values["constant"]["A"]
                ))
            
            brk.constant_animations.append(anim)
        
        return brk 

    
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("input",
                        help="Path to brk or json-formatted text file.")
    parser.add_argument("output", default=None, nargs = '?',
                        help=(
                            "Path to which the converted file should be written. "
                            "If input was a BRK, writes a json file. If input was a json file, writes a BRK."
                            "If left out, output defaults to <input>.json or <input>.brk."
                        ))

    args = parser.parse_args()

    if args.ndigits < 0:
        ndigits = None
    else:
        ndigits = args.ndigits


    with open(args.input, "rb") as f:
        if f.read(8) == BRKFILEMAGIC:
            brk_to_json = True
        else:
            brk_to_json = False

    if args.output is None:
        if brk_to_json:
            output = args.input+".json"
        else:
            output = args.input+".brk"
    else:
        output = args.output

    if brk_to_json:
        with open(args.input, "rb") as f:
            brk = BRKAnim.from_brk(f)
        with open(output, "w") as f:
            brk.dump(f, digits=ndigits)
    else:
        # Detect BOM of input file
        with open(args.input, "rb") as f:
            bom = f.read(4)
        
        if bom.startswith(codecs.BOM_UTF8):
            encoding = "utf-8-bom"
        elif bom.startswith(codecs.BOM_UTF32_LE) or bom.startswith(codecs.BOM_UTF32_BE):
            encoding = "utf-32"
        elif bom.startswith(codecs.BOM_UTF16_LE) or bom.startswith(codecs.BOM_UTF16_BE):
            encoding = "utf-16"
        else:
            encoding = "utf-8"
        
        print("Assuming encoding of input file:", encoding)
        
        with io.open(args.input, "r", encoding=encoding) as f:
            #with open(args.input, "rb") as f:
            brk = BRKAnim.from_json(f)
        with open(output, "wb") as f:
            brk.write_brk(f)
