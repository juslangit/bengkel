# Borrowed motion

Drop `.fbx` animation clips in this folder and they appear in boneka's
**"or borrow a motion capture clip"** menu, ready to apply to whatever is
rigged.

Mixamo is the usual source: pick an animation, download it as **FBX Binary**
with **Skin: without skin**, and drop the file here. boneka translates the
bone names (`mixamorig:LeftArm` and friends) onto its own skeleton, and reads
each turn in the source rig's own space before writing it into ours — so the
two rigs don't have to agree on rest pose, bone length or roll, only on which
bone is which.

The result is close rather than exact. A clip recorded on a tall thin skeleton
put onto a short fat one will need its amount dialling back; that is the nature
of retargeting, not a bug.

Clips are ignored by git, because they aren't ours to redistribute.
