## uBITX CEC Desktop — rebuild branch

Five files: a working interface mockup, the model behind it, a stub that
stands in for the radio, and the reasoning for both.

Nothing here talks to a rig. The point is that the SHAPE is right, so the
transport can be swapped in without rewiring the interface.

### Running it

```bash
python3 ubitx_cec_desktop.py
```

Needs `scustomtkinter` installed, with a theme block for every widget it
uses — including `sCTkNotebook`, which is the newest. A missing key fails
loudly at construction and names itself.

### The files

| File | What it is |
| :--- | :--- |
| `ARCHITECTURE.md` | The layering, the rules, and what moves where. Read first. |
| `TODO.md` | Outstanding work, including bugs in the current application. |
| `radio_state.py` | The model. What the hardware last reported, in one form. |
| `stub_radio.py` | Stands in for `piRadio`: accepts commands, confirms them later. |
| `ubitx_mockup.py` | The interface, reading state and sending commands. |

### The one rule

**No view code writes to the state.** A control sends a command; the
confirmation updates the state; the state triggers one redraw. Grep for
`self.radio.<something> =` outside the transport — the only hits should be
seeding initial values at startup.

That is the discipline everything else depends on, and it is the one worth
checking as the port grows.

### Worth trying in the mockup

* Click a digit in either frequency, then turn that panel's dial
* Split — TX moves to VFO B, the offset buttons wake up, nothing shifts position
* RIT — tuning the receive side moves the offset, and the base stays visible
* Simulate transmit, bottom right — the meters swap roles
* Band — sets the mode by convention, and the filter with it

### Open question

Does the rig report `va`/`vb` continuously, or only at startup? Three
commands report two values — `vc`/`cc` for the displayed VFO, `va`/`vb` for A
and B, `cv` for which is active — and if A and B only arrive once, the
standby readout goes stale out of split. That is the one finding that would
change the model.
