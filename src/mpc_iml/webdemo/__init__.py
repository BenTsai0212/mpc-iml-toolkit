"""A web demo of the `ensemble` preset without hardware (#166).

`sim` runs the real `ensemble` rules offline on a step grid of drums, with a
simulated MIDI clock, and returns the notes and one row per bar. `synth` renders
them with numpy. `app` is the Gradio page, installed with the optional `demo` extra
and run with `python -m mpc_iml.webdemo`; only `app.build` imports Gradio.
"""
