import sys
sys.path.insert(0, "c:/Users/USER/Downloads/hear-py")

from scratch.test_real_lambda_dialog_flows import make_context, setup_mock_environment, make_envelope
import main

persistence_adapter, container = setup_mock_environment()
ctx = make_context()
env2 = make_envelope(intent_name='PlayContentIntent', slots={'topic': 'creators'})

skill = main._application.skill()
for h in skill.request_handlers:
    orig_can = h.can_handle
    def make_can(handler, orig):
        def can(inp):
            c = orig(inp)
            if c:
                print("Matched handler:", handler.__class__.__name__)
            return c
        return can
    h.can_handle = make_can(h, orig_can)

resp2 = main.handler(env2, ctx)
print("resp2:", resp2)
