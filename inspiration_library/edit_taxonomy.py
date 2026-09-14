"""Shared behavioral definitions, not quotas or semantic keyword classifiers."""

WEBCOMPASS_EDIT_FUNCTIONS = {
    "Data Table": "Manage records in rows and columns; sorting, filtering, pagination or selection operates on the same data, with consistent results and summaries.",
    "Rich Text Editor": "Edit selections or blocks with semantic formatting, headings, lists, links or media and retain a serializable document state.",
    "Drag & Drop Interface": "Use a real drag and drop gesture to change object order, grouping or ownership, with valid drop targets and visible feedback.",
    "Tree View": "Navigate hierarchical parent-child data through expansion, collapse, selection or search, maintaining the relevant hierarchy state.",
    "Real-time Dashboard": "Update related metrics, charts and refresh indicators over time from a consistent event or data source; explicitly identify simulation when used.",
    "Infinite Scroll": "Append further batches near the end of a scrolling list, managing pending requests, duplicates, order and exhaustion.",
    "Async Form Validation": "Check input asynchronously with pending, valid and invalid states, stale-response protection and consistent submission eligibility.",
    "File Upload with Progress": "Select or drop files and manage validation, per-file progress and completion, with relevant cancellation or recovery behavior.",
    "Parallax Scrolling": "Move visual layers at different rates or directions during scrolling to create relative displacement and depth.",
    "Page Transitions": "Coordinate outgoing and incoming page/view states during navigation, including intermediate animation and a correct interactive final state.",
    "Particle Effects": "Animate a system of particles over time with specified motion, proximity or input-driven behavior.",
    "Skeleton Loading": "Show placeholders corresponding to the eventual content layout while loading, then replace them with content with controlled layout movement.",
    "Shopping Cart": "Manage a selected item collection through adding, removing, quantities or aggregate totals and synchronized basket views; items need not be merchandise.",
    "User Authentication": "Maintain sign-in, registration or sign-out and session-dependent navigation/user UI; distinguish simulated frontend sessions from real authentication.",
    "Multi-step Wizard": "Complete one workflow through ordered steps with progress, forward validation, backward navigation, retained input and final confirmation.",
    "Notification Center": "Manage an event inbox with synchronized unread counts, read/delete actions and relevant grouping or arrival of new notifications.",
}
WEBCOMPASS_EDIT_TYPES = tuple(WEBCOMPASS_EDIT_FUNCTIONS)

PRODUCT_EDIT_POLICY = """Internal product-first design guidance and classification reference:
Follow this order: product direction -> capability needed to advance that direction -> prefer a
functional design that realizes a suitable family below -> instantiate the Edit and classify it.
The product goal and actual current state determine the user need first. The families guide how to
design that needed capability; never sample a type first and invent a product need to accommodate it.
Apply this guidance while planning capabilities, not only when labeling a finished instruction.
For a needed capability, prefer a coherent design that implements a suitable family's core user
actions, state changes and visible results. State the product contribution and concrete behavior
in the capability plan's existing contribution_to_goal and completion_criteria fields.
Treat the interaction mechanism in an UNEXECUTED plan as a proposal, not a product requirement.
Preserve the job the user needs done, but reconsider how the user performs it. Replacing a proposed
mechanism with an equally suitable family-based interaction is allowed within that same capability;
it is not unrelated scope merely because the previous draft used a simpler mechanism.
When such a natural family design exists, actually use it in the planned behavior. Do not keep the
old mechanism and then argue that its unchanged behavior is outside the taxonomy.
When no family fits that useful increment without distorting the product need, keep the increment
and classify it as an extension with a concrete product-need explanation. Merely saying that the
previous design lacks a family's behavior is not such an explanation. Extensions are for justified needs,
not the default design path. Reconsider unexecuted designs while retaining the product direction,
sampled length and completed prefix. Do not add unrelated effects, inflate scope, or merge separately
useful increments merely to obtain an official label. There is no per-chain type quota or checklist.
Never mislabel an unrelated feature to claim benchmark coverage.
Every Edit adds one independently useful capability; helper controls belong with their feature.
Classify actual behavior, not nouns: a toast is not a notification center, a favorite toggle is not
a cart, a plain textarea is not a rich text editor, synchronous validation is not asynchronous.
The instruction itself must not mention this taxonomy, benchmarks, donor IDs or internal state IDs.
Classification JSON has primary:{taxonomy,type}, secondary:[{taxonomy,type}], and reason:string.
The taxonomy field must be exactly "webcompass" or "extension", never a capability family name.
Use "webcompass" only with one of the exact official type names below. For other behaviors use
"extension" with a descriptive type name. secondary may be empty. reason explains observed behavior.
""" + "\n".join(f"- {name}: {description}" for name, description in WEBCOMPASS_EDIT_FUNCTIONS.items())


def validate_classification(value):
    if not isinstance(value, dict) or not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise ValueError("classification needs a behavioral reason")
    primary, secondary = value.get("primary"), value.get("secondary", [])
    if not isinstance(secondary, list):
        raise ValueError("secondary classifications must be a list")
    seen = set()
    for item in [primary, *secondary]:
        if not isinstance(item, dict) or item.get("taxonomy") not in {"webcompass", "extension"}:
            raise ValueError("classification taxonomy must be webcompass or extension")
        name = item.get("type")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("classification type must be nonempty")
        if (item["taxonomy"] == "webcompass") != (name in WEBCOMPASS_EDIT_FUNCTIONS):
            raise ValueError("official names and extension names must remain distinct")
        key = (item["taxonomy"], name)
        if key in seen:
            raise ValueError("duplicate classification")
        seen.add(key)
    return {"primary": primary, "secondary": secondary, "reason": value["reason"]}
