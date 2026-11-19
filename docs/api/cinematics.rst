Cinematics
==========

Domain-level camera-shot builders, built on :class:`~dazpy.DazCamera` and
:class:`~dazpy.DazScene`. Each is an adapter over the typed models in
:doc:`shots`: ``spec.to_shot()`` returns the equivalent
:class:`~dazpy.shots.Shot`. For named shot types, coverage, the
180-degree rule and camera moves built from actor positions, see
:doc:`shot_library`.

CinematicStaticShot
--------------------

.. autoclass:: dazpy.CinematicStaticShot
   :members:
   :undoc-members:
   :show-inheritance:

.. autofunction:: dazpy.apply_static_shot

OrbitCamera
-----------

.. autoclass:: dazpy.OrbitCamera
   :members:
   :undoc-members:
   :show-inheritance:

.. autofunction:: dazpy.apply_orbit_camera

FrameSubject
------------

.. autoclass:: dazpy.FrameSubject
   :members:
   :undoc-members:
   :show-inheritance:

.. autofunction:: dazpy.apply_frame_subject

CinematicAnimatedShot
----------------------

Waypoints are :class:`dazpy.shots.CameraKeyframe` (also importable from
``dazpy.cinematics``).

.. autoclass:: dazpy.CinematicAnimatedShot
   :members:
   :undoc-members:
   :show-inheritance:

.. autofunction:: dazpy.apply_animated_shot
