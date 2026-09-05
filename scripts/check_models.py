#!/usr/bin/env python3
"""Run real inference on a blank image, without opening the webcam."""
import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", help="Directory containing hand_landmarker.task and pose_landmarker_lite.task")
    args = parser.parse_args()
    from pathlib import Path
    import mediapipe as mp
    import numpy as np

    folder = Path(args.model_dir)
    base, vision = mp.tasks.BaseOptions, mp.tasks.vision
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((480, 640, 3), dtype=np.uint8))
    with vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=base(model_asset_path=str(folder / "hand_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_hands=2)) as hands:
        assert not hands.detect_for_video(image, 1).hand_landmarks
    with vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=base(model_asset_path=str(folder / "pose_landmarker_lite.task")),
        running_mode=vision.RunningMode.VIDEO)) as pose:
        assert not pose.detect_for_video(image, 1).pose_landmarks
    print("Hand and pose models loaded; blank-frame inference passed.")


if __name__ == "__main__":
    main()
