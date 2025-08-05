from app.feeder import Feeder
import asyncio
import argparse


async def main():
    parser = argparse.ArgumentParser(description="Run Feeder to generate ML dataset")
    parser.add_argument("--num-points", type=int, required=True,
                        help="Number of data points to generate")
    args = parser.parse_args()

    async with Feeder() as feeder:
        await feeder.run(args.num_points)


if __name__ == "__main__":
    asyncio.run(main())
