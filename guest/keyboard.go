package main

//go:generate sh -c "python3 gen_keysyms.py /usr/include/X11/keysymdef.h /usr/include/X11/XF86keysym.h > keysyms.go && gofmt -w keysyms.go"

import (
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jezek/xgb"
	"github.com/jezek/xgb/xproto"
	"github.com/jezek/xgb/xtest"
)

type keyboardArgs struct {
	Display string `json:"display"`
	// keys is xdotool's syntax: "ctrl+shift+t", or several combinations separated by spaces
	Keys    string `json:"keys"`
	Text    string `json:"text"`
	DelayMs int    `json:"delay"`
}

// aliases are the short names xdotool accepts, plus a few that models often send.
var aliases = map[string]string{
	"ctrl": "Control_L", "control": "Control_L", "alt": "Alt_L", "shift": "Shift_L", "super": "Super_L",
	"meta": "Meta_L", "win": "Super_L", "cmd": "Super_L", "enter": "Return", "esc": "Escape", "del": "Delete",
	"backspace": "BackSpace", "pageup": "Prior", "pagedown": "Next", "pgup": "Prior", "pgdn": "Next",
	"ins": "Insert", "capslock": "Caps_Lock", "arrowup": "Up", "arrowdown": "Down", "arrowleft": "Left",
	"arrowright": "Right",
}

// foldedNames looks names up ignoring case; a spelling shared by two keysyms (Ccedilla, ccedilla) maps to 0.
var foldedNames = func() map[string]uint32 {
	folded := map[string]uint32{}
	for name, sym := range keysymNames {
		key := strings.ToLower(name)
		if prev, ok := folded[key]; ok && prev != sym {
			folded[key] = 0
		} else {
			folded[key] = sym
		}
	}
	return folded
}()

func keysym(name string) (uint32, error) {
	if sym, ok := keysymNames[name]; ok {
		return sym, nil
	}
	if alias, ok := aliases[strings.ToLower(name)]; ok {
		return keysymNames[alias], nil
	}
	if r := []rune(name); len(r) == 1 {
		return runeKeysym(r[0]), nil
	}
	if sym := foldedNames[strings.ToLower(name)]; sym != 0 {
		return sym, nil
	}
	return 0, fmt.Errorf("unknown key %q", name)
}

func runeKeysym(r rune) uint32 {
	switch r {
	case '\n', '\r':
		return 0xff0d // Return
	case '\t':
		return 0xff09 // Tab
	case '\b':
		return 0xff08 // BackSpace
	}
	if r >= 0x20 && r <= 0x7e || r >= 0xa0 && r <= 0xff {
		return uint32(r) // Latin-1 keysyms are their code points
	}
	return 0x01000000 | uint32(r)
}

// keyboard types through XTest. A keysym missing from the keymap (é on a US layout, emoji) is mapped onto a spare
// keycode for the duration of the call, as xdotool does.
type keyboard struct {
	x        *xgb.Conn
	root     xproto.Window
	min      xproto.Keycode
	per      int
	syms     []xproto.Keysym
	spare    []xproto.Keycode
	next     int
	remapped []xproto.Keycode
	held     []xproto.Keycode
}

func newKeyboard(x *xgb.Conn, root xproto.Window) (*keyboard, error) {
	setup := xproto.Setup(x)
	count := int(setup.MaxKeycode) - int(setup.MinKeycode) + 1
	reply, err := xproto.GetKeyboardMapping(x, setup.MinKeycode, byte(count)).Reply()
	if err != nil {
		return nil, err
	}
	k := &keyboard{x: x, root: root, min: setup.MinKeycode, per: int(reply.KeysymsPerKeycode), syms: reply.Keysyms}
	for i := range count {
		if !slices.ContainsFunc(k.row(i), func(s xproto.Keysym) bool { return s != 0 }) {
			k.spare = append(k.spare, k.min+xproto.Keycode(i))
		}
	}
	return k, nil
}

func (k *keyboard) row(i int) []xproto.Keysym {
	return k.syms[i*k.per : (i+1)*k.per]
}

// find returns the keycode for a keysym and whether it needs shift, looking only at the plain and shifted levels.
func (k *keyboard) find(sym uint32) (xproto.Keycode, bool, bool) {
	for level := range min(2, k.per) {
		for i := range len(k.syms) / k.per {
			if uint32(k.row(i)[level]) == sym {
				return k.min + xproto.Keycode(i), level == 1, true
			}
		}
	}
	return 0, false, false
}

func (k *keyboard) remap(sym uint32) (xproto.Keycode, error) {
	if len(k.spare) == 0 {
		return 0, fmt.Errorf("no spare keycode to type keysym %#x", sym)
	}
	code := k.spare[k.next%len(k.spare)]
	k.next++
	if err := k.setRow(code, xproto.Keysym(sym)); err != nil {
		return 0, err
	}
	if !slices.Contains(k.remapped, code) {
		k.remapped = append(k.remapped, code)
	}
	return code, nil
}

func (k *keyboard) setRow(code xproto.Keycode, sym xproto.Keysym) error {
	row := slices.Repeat([]xproto.Keysym{sym}, k.per)
	if err := xproto.ChangeKeyboardMappingChecked(k.x, 1, code, byte(k.per), row).Check(); err != nil {
		return err
	}
	copy(k.row(int(code-k.min)), row)
	return nil
}

func (k *keyboard) fake(event byte, code xproto.Keycode) error {
	return xtest.FakeInputChecked(k.x, event, byte(code), 0, k.root, 0, 0, 0).Check()
}

func (k *keyboard) press(code xproto.Keycode) error {
	if err := k.fake(xproto.KeyPress, code); err != nil {
		return err
	}
	k.held = append(k.held, code)
	return nil
}

func (k *keyboard) release(code xproto.Keycode) error {
	if i := slices.Index(k.held, code); i >= 0 {
		k.held = slices.Delete(k.held, i, i+1)
	}
	return k.fake(xproto.KeyRelease, code)
}

// down presses a keysym, with shift first when it sits on the shifted level, and returns the keycodes it pressed.
func (k *keyboard) down(sym uint32) ([]xproto.Keycode, error) {
	code, shifted, ok := k.find(sym)
	if !ok {
		var err error
		if code, err = k.remap(sym); err != nil {
			return nil, err
		}
	}
	var pressed []xproto.Keycode
	if shifted {
		shift, _, ok := k.find(keysymNames["Shift_L"])
		if !ok {
			return nil, errors.New("the keymap has no Shift_L")
		}
		if err := k.press(shift); err != nil {
			return nil, err
		}
		pressed = append(pressed, shift)
	}
	if err := k.press(code); err != nil {
		return pressed, err
	}
	return append(pressed, code), nil
}

// combo presses each key in order and releases them in reverse, like xdotool key.
func (k *keyboard) combo(names []string) error {
	var pressed []xproto.Keycode
	for _, name := range names {
		sym, err := keysym(name)
		if err != nil {
			return err
		}
		codes, err := k.down(sym)
		pressed = append(pressed, codes...)
		if err != nil {
			return err
		}
	}
	for _, code := range slices.Backward(pressed) {
		if err := k.release(code); err != nil {
			return err
		}
	}
	return nil
}

// close releases anything a failed call left down and gives remapped keycodes back.
func (k *keyboard) close() {
	for _, code := range slices.Backward(k.held) {
		k.fake(xproto.KeyRelease, code)
	}
	for _, code := range k.remapped {
		k.setRow(code, 0)
	}
}

func splitCombo(combo string) ([]string, error) {
	if combo == "+" {
		return []string{"plus"}, nil
	}
	names := strings.Split(combo, "+")
	if slices.Contains(names, "") {
		return nil, fmt.Errorf("bad key combination %q", combo)
	}
	return names, nil
}

func keyboardOp(c call) (any, []byte, error) {
	a := keyboardArgs{Display: ":1", DelayMs: 12}
	if err := json.Unmarshal(c.args, &a); err != nil {
		return nil, nil, err
	}
	if (a.Keys == "") == (a.Text == "") {
		return nil, nil, errors.New("send either keys or text")
	}
	// parse first, so a typo fails before anything is pressed
	var combos [][]string
	for _, combo := range strings.Fields(a.Keys) {
		names, err := splitCombo(combo)
		if err != nil {
			return nil, nil, err
		}
		for _, name := range names {
			if _, err := keysym(name); err != nil {
				return nil, nil, err
			}
		}
		combos = append(combos, names)
	}
	if a.Keys != "" && len(combos) == 0 {
		return nil, nil, errors.New("keys is blank")
	}
	x, root, err := xtestConn(a.Display)
	if err != nil {
		return nil, nil, err
	}
	defer x.Close()
	k, err := newKeyboard(x, root)
	if err != nil {
		return nil, nil, err
	}
	defer k.close()
	delay := time.Duration(max(a.DelayMs, 0)) * time.Millisecond
	if a.Text != "" {
		text := strings.ReplaceAll(a.Text, "\r\n", "\n")
		n := 0
		for _, r := range text {
			if n > 0 {
				time.Sleep(delay)
			}
			codes, err := k.down(runeKeysym(r))
			if err != nil {
				return nil, nil, err
			}
			for _, code := range slices.Backward(codes) {
				if err := k.release(code); err != nil {
					return nil, nil, err
				}
			}
			n++
		}
		return map[string]any{"typed": n}, nil, nil
	}
	for i, names := range combos {
		if i > 0 {
			time.Sleep(delay)
		}
		if err := k.combo(names); err != nil {
			return nil, nil, err
		}
	}
	return map[string]any{"combos": len(combos)}, nil, nil
}
