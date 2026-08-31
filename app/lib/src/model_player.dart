/// The model, playing.
///
/// The creator's point: you cannot judge lighting on a still, and you certainly
/// cannot judge it on a quantised sprite sheet where the tile vocabulary has
/// already thrown away the shading you are trying to tune. So the preview plays
/// the ACTUAL render — Blender's own output of the actual model, with the actual
/// materials and the light currently being dragged — at the clip's own rate.
library;

import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

class ModelPlayer extends StatefulWidget {
  const ModelPlayer({super.key, required this.frames, this.fps = 12, this.playing = true});

  final List<Uint8List> frames;
  final double fps;
  final bool playing;

  @override
  State<ModelPlayer> createState() => ModelPlayerState();
}

class ModelPlayerState extends State<ModelPlayer> {
  Timer? _timer;
  int _index = 0;

  @override
  void initState() {
    super.initState();
    _restart();
  }

  @override
  void didUpdateWidget(ModelPlayer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.frames.length != widget.frames.length ||
        oldWidget.fps != widget.fps ||
        oldWidget.playing != widget.playing) {
      _index = 0;
      _restart();
    }
  }

  void _restart() {
    _timer?.cancel();
    if (!widget.playing || widget.frames.length < 2) return;
    final period = Duration(milliseconds: (1000 / widget.fps).round().clamp(16, 2000));
    _timer = Timer.periodic(period, (_) {
      if (!mounted) return;
      setState(() => _index = (_index + 1) % widget.frames.length);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.frames.isEmpty) return const SizedBox.shrink();
    final frame = widget.frames[_index.clamp(0, widget.frames.length - 1)];
    return Column(mainAxisSize: MainAxisSize.min, children: [
      // Checkerboard, because these renders are cut-outs and a flat backdrop
      // would hide an alpha problem until it reached a game engine.
      DecoratedBox(
        decoration: const BoxDecoration(color: Color(0xFF14161A)),
        child: Image.memory(frame, gaplessPlayback: true, filterQuality: FilterQuality.medium),
      ),
      const SizedBox(height: 6),
      Text('frame ${_index + 1}/${widget.frames.length}'
           '${widget.playing ? '' : ' · paused'}',
          style: const TextStyle(fontSize: 10, color: Colors.white38)),
    ]);
  }
}
