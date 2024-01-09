import sys
import re

from prompt_toolkit import Application, HTML
from prompt_toolkit.application import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import input_dialog

# Diskette
SECTOR_SIZE, SECTOR, TRACK = 512, 18, 160
SECTOR_VISIBLE  = 0
# SECTOR_READSIZE = SECTOR_SIZE*SECTOR*TRACK
SECTOR_READSIZE = SECTOR_SIZE*120
BARR            = None

# GUI (prompt_toolkit)
INFOTEMPLATE    = '<aaa fg="ansiwhite" bg="ansigreen">Sector: {sector:4d} (0x{sector_addr:04X})| &#8593;, &#8595;: dec, inc sector; C-s: search, /: next; C-q: quit</aaa>'

# Search state
SEARCH_START, SEARCH_REG = None, None

# Decoding
CODEPAGE = [
    ( '\\x8d', '\u00e8' ), ( '\\x8c', '\u00e9' ),
    ( '\\x81', '\u00e0' ), ( '\\x8f', '\u00ea' ),
    ( '\\x89', '\u00f9' ), ( '\\x93', '\u00f4' ),
    ( '\\x9c', '\u00e7' ), ( '\\x87', '\u00ee' ), ( '__', '' )
    ]
CHAR_REPLACEMENT = ord( '_' )

# See also:[[https://github.com/rtaylor187/CanonTxtCvt/blob/master/Convert.cs#L144]]

def rawparse( arr, beg ):
    state      = 0
    ch, lastch = 0, 0
    pos        = beg
    while 0 <= state:
        lastch = ch
        ch = arr[ pos ]
        pos += 1
        # START
        if 0 == state :
            if 3 == ch :
                state = -2
            elif ch in [ 16, 17, 18, 19, 20, 21 ]:
                state = ch - 15
                arr[ pos-1 ] = CHAR_REPLACEMENT
            else:
                retb = bytearray()
                retb.extend( map( ord, "Error block byte %d\n" % ch  ) )
                return pos-beg, retb 
        # 0x10 FORMAT/STYLE
        elif 1 == state :
            if 2 == ch :
                pass
            elif 16 == ch :
                state = 0
                arr[ pos-1 ] = CHAR_REPLACEMENT
            elif ch in [ ord('0'), ord('2'), ord('@'),
                         ord('B'), ord('D'), ord('F'),
                         ord('H'), ord('J'), ord(' ') ] :
                fmVal, toVal, closing = arr[ pos ], arr[ pos+1 ], arr[ pos+2 ]
                arr[ pos ], arr[ pos+1 ], arr[ pos+2 ] = CHAR_REPLACEMENT, CHAR_REPLACEMENT, CHAR_REPLACEMENT
                arr[ pos-1 ] = CHAR_REPLACEMENT
                pos += 3
            else:
                pass
        # 0x11 PARAGRAPH/PAGE BREAK/TAB/JUSTIFIED(L,C,R)
        elif 2 == state :
            if 3 == ch :
                state = -2
            elif 17 == ch :
                state = 0
                arr[ pos-1 ] = CHAR_REPLACEMENT
            elif 34 == ch :
                arr[ pos-1 ] = 10
            elif 128 == ch :
                arr[ pos-1 ] = 9
            elif 129 == ch :
                arr[ pos-1 ] = 10
            elif ch in [ 132, 133 ] :
                arr[ pos-1 ] = CHAR_REPLACEMENT
            else:
                arr[ pos-1 ] = CHAR_REPLACEMENT
        # 0x12 FORMAT CHANGE?
        elif 3 == state :
            if 18 == ch :
                state = 0
            arr[ pos-1 ] = CHAR_REPLACEMENT
        # 0x13 TEXT: BASE CODE PAGE 0x04 <x> <y> 0x05
        elif 4 == state :
            if 3 == ch :
                state = -2
            elif 19 == ch :
                state = 0
                arr[ pos-1 ] = CHAR_REPLACEMENT
            elif 4 == ch:
                fmVal, toVal, closing = arr[ pos ], arr[ pos+1 ], arr[ pos+2 ]
                arr[ pos ], arr[ pos+1 ], arr[ pos+2 ] = CHAR_REPLACEMENT, CHAR_REPLACEMENT, CHAR_REPLACEMENT
                arr[ pos-1 ] = CHAR_REPLACEMENT
                pos += 3
            else:
                pass
        # 0x14 TEXT: SYMBOL CODE PAGE
        elif 5 == state :
            if 20 == ch :
                state = 0
                arr[ pos-1 ] = CHAR_REPLACEMENT
            else:
                pass
        # 0x15 0x80
        elif 6 == state :
            if 21 == ch or 128 == ch :
                state = 0
                arr[ pos-1 ] = CHAR_REPLACEMENT
            else:
                pass
            
    return pos-beg, arr[ beg:pos ]
        

def rawdecode( arr, beg, end=None ):
    """ Decode the raw bytearray `arr' from SW file into utf-8 string

    Note: without the last argument `end', scans for the end of text
    when parsing.
    """
    global CODEPAGE
    if None == end:
        end03, local_arr = rawparse( arr, beg )
    else:
        end03, local_arr = end, arr[ beg:end ]
        
    decoded = local_arr.decode( encoding='utf-8', errors = 'backslashreplace' )
    for (src,tgt)  in CODEPAGE:
        decoded = decoded.replace( src, tgt )
    return decoded, end03
   

def raw2content( arr, idx ):
    s        = '\nDocHdr: {dh:01X}, File: {fn}\nTrigger: {trigger:04X}, Len: {len:6d}, End: {end:6d}, Char: {c:01X}\n'
    offset   = idx+9+2+8+8+8+4
    dh       = arr[ offset ]
    offset  += 1+12+8+3
    fn, end  = rawdecode( arr, offset, offset+8 )
    offset  += 8+3+10+36
    trigger  = int.from_bytes(arr[offset:offset+2])
    length   = int.from_bytes( arr[offset+2:offset+6], "little" )
    c        = arr[offset+142]
    if 159 == dh and 5979 == trigger and 18 == c:
        with open( "out.txt", "a", encoding='utf-8' ) as out:
            # txt, end = rawdecode( arr, offset+142, offset+(length-136) )
            txt, end = rawdecode( arr, offset+142 )
            out.write( s.format( dh=dh, fn=fn, trigger=trigger, len=length, end=end, c=c ) )
            out.write( txt )

    
def sector2ascii( arr ):
    str = ""
    for row in range( 32 ):
        for x in arr[row*16:(row+1)*16]:
            str += "." if x<32 or x>126 else chr(x)
        str += "\n"
    return str

def sector2binary( arr ):
    str = ""
    for row in range( 32 ):
        str += '{0:02X} '.format( row )
        for i in range( row*16, (row+1)*16, 2 ):
            str += arr[ i:i+2 ].hex() + ' '
        str = str[ :len(str)-1 ] + '\n'
    return str


if __name__ == '__main__':
    Buff_left, Buff_right, Buff_args = Buffer(), Buffer(), Buffer()
    FTC_info = FormattedTextControl(
        text = HTML( INFOTEMPLATE.format(sector=SECTOR_VISIBLE,
                                         sector_addr=SECTOR_SIZE*SECTOR_VISIBLE) ) )

    root_container = HSplit([
        Window( height = 1, content = FTC_info ),
        Window( height = 1, content = BufferControl( Buff_args ) ),
        VSplit([
            # One window that holds the BufferControl with the default buffer on
            # the left.
            Window( content = BufferControl( Buff_left ) ),

            # A vertical line in the middle. We explicitly specify the width, to
            # make sure that the layout engine will not try to divide the whole
            # width by three for all these windows. The window will simply fill its
            # content by repeating this character.
            # Window(width=1, char='|'),

            # Display the text 'Hello world' on the right.
            Window( content = BufferControl( Buff_right ) ),
        ])
    ])

    layout = Layout(root_container)
    
    kb = KeyBindings()

    @kb.add('up')
    def up_( event ):
        global SECTOR_VISIBLE
        if SECTOR_VISIBLE > 0:
            SECTOR_VISIBLE -= 1
            buff2sector( BARR, SECTOR_VISIBLE )
    
    @kb.add('down')
    def down_( event ):
        global SECTOR_READSIZE, SECTOR_VISIBLE
        if SECTOR_VISIBLE + 1 < SECTOR_READSIZE // SECTOR_SIZE :
            SECTOR_VISIBLE += 1
            buff2sector( BARR, SECTOR_VISIBLE )
    
    @kb.add('c-s')
    def search_( event ):
        global SECTOR_READSIZE, SECTOR_VISIBLE, BARR, SEARCH_START, SEARCH_REG
        # target = bytes( Buff_args.text, 'ascii' )
        target = bytes( 'CANONETW1', 'ascii' )
        if None == target : return
        SEARCH_REG = re.compile( target )
        m = re.search( SEARCH_REG, BARR )
        if None == m : return
        raw2content( BARR, m.start() )
        SECTOR_VISIBLE = m.start() // SECTOR_SIZE
        SEARCH_START   = m.end()
        buff2sector( BARR, SECTOR_VISIBLE )

    @kb.add('/')
    def searchnext_( event ):
        global SECTOR_READSIZE, SECTOR_VISIBLE, BARR, SEARCH_START, SEARCH_REG
        if None == SEARCH_REG or None == SEARCH_START : return
        m = re.search( SEARCH_REG, BARR[SEARCH_START:] )
        if None == m : return
        raw2content( BARR, SEARCH_START + m.start() )
        SECTOR_VISIBLE = (SEARCH_START + m.start()) // SECTOR_SIZE
        SEARCH_START   = SEARCH_START + m.end()
        buff2sector( BARR, SECTOR_VISIBLE )
        

    @kb.add('c-q')
    def exit_(event):
        """
        Pressing Ctrl-Q will exit the user interface.
        
        Setting a return value means: quit the event loop that drives the user
        interface and return this value from the `Application.run()` call.
        """
        event.app.exit()
        
    app = Application(layout=layout, key_bindings=kb, full_screen=True)

        
    def buff2sector( arr, sector ):
        Buff_right.reset()
        Buff_right.insert_text(
            sector2ascii( arr[sector*SECTOR_SIZE:(sector+1)*SECTOR_SIZE] ) )
        Buff_left.reset()
        Buff_left.insert_text(
            sector2binary( arr[sector*SECTOR_SIZE:(sector+1)*SECTOR_SIZE] ) )
        FTC_info.text = HTML(
            INFOTEMPLATE.format(sector=SECTOR_VISIBLE,
                                sector_addr=SECTOR_SIZE*SECTOR_VISIBLE) )
        get_app().invalidate()
        
    count = 0
    with open( '\\\\.\\A:', 'rb' ) as f:
        for data in iter( lambda: f.read( SECTOR_READSIZE ), '' ):
            if count > 0:
                break
            BARR = bytearray( data )
            count += 1
    print( "Read (bytes):", SECTOR_READSIZE )        
    buff2sector( BARR, SECTOR_VISIBLE )
    
    app.run() # You won't be able to Exit this app
