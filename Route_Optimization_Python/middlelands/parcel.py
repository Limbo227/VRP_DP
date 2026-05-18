import random
random.seed(42)
def create_parcel():
    """
    Randomly select a parcel type with pre-set weight and volume:
    - 10kg, 0.050 m³
    - 20kg, 0.100 m³
    - 30kg, 0.150 m³
    """
    parcel_types = [
        {"weight": 10, "volume": 0.10},
        {"weight": 20, "volume": 0.150},
        {"weight": 30, "volume": 0.200},
    ]
    return random.choice(parcel_types)

# Example usage: attach parcels to each delivery row
parcels = [create_parcel() for _ in range(300)]

print(sum(parcel["weight"] for parcel in parcels))
print(sum(parcel["volume"] for parcel in parcels))
print(len(parcels))
print(len([parcel["weight"] for parcel in parcels if parcel["weight"] == 10]))
print(len([parcel["weight"] for parcel in parcels if parcel["weight"] == 20]))
print(len([parcel["weight"] for parcel in parcels if parcel["weight"] == 30]))